//! Low-level Rust hot paths for Sensei compression.
//!
//! Optional accelerator: Python soft-imports `sensei_core` and uses it when
//! present, falling back to the pure-Python implementation otherwise. Output is
//! byte-compatible with `SmartCrusher._to_csv_schema` for the tested shapes.

use pyo3::prelude::*;
use serde_json::Value;
use std::collections::BTreeSet;

const MAX_VALUE_LEN: usize = 200;

/// Truncate over-long strings, matching the Python `_compress_string`.
fn compress_string(s: &str) -> String {
    let n = s.chars().count();
    if n > MAX_VALUE_LEN {
        let head: String = s.chars().take(MAX_VALUE_LEN).collect();
        format!("{head}…<+{}c>", n - MAX_VALUE_LEN)
    } else {
        s.to_string()
    }
}

/// Normalize a JSON value to a single CSV cell string.
fn scalar(v: &Value) -> String {
    match v {
        Value::Null => String::new(),
        Value::Bool(b) => if *b { "true".into() } else { "false".into() },
        Value::Number(n) => n.to_string(),
        Value::String(s) => compress_string(s),
        other => serde_json::to_string(other).unwrap_or_default(),
    }
}

/// CSV-escape a field (RFC4180-ish).
fn csv_field(s: &str) -> String {
    if s.contains([',', '"', '\n', '\r']) {
        format!("\"{}\"", s.replace('"', "\"\""))
    } else {
        s.to_string()
    }
}

/// Sorted intersection of keys if `arr` is a homogeneous dict array worth tabulating.
fn table_keys(arr: &[Value]) -> Option<Vec<String>> {
    if arr.len() < 3 {
        return None;
    }
    let mut common: Option<BTreeSet<String>> = None;
    for v in arr {
        let obj = v.as_object()?;
        let keys: BTreeSet<String> = obj.keys().cloned().collect();
        common = Some(match common {
            None => keys,
            Some(c) => c.intersection(&keys).cloned().collect(),
        });
    }
    let common = common.unwrap_or_default();
    (common.len() >= 2).then(|| common.into_iter().collect())
}

/// Render a homogeneous JSON dict-array as a CSV-schema table.
/// Returns `None` when the input isn't a tabular array (caller falls back).
#[pyfunction]
fn csv_schema(json_str: &str) -> PyResult<Option<String>> {
    let data: Value = match serde_json::from_str(json_str) {
        Ok(v) => v,
        Err(_) => return Ok(None),
    };
    let Some(arr) = data.as_array() else {
        return Ok(None);
    };
    let Some(keys) = table_keys(arr) else {
        return Ok(None);
    };

    let rows: Vec<Vec<String>> = arr
        .iter()
        .map(|item| {
            let obj = item.as_object().unwrap();
            keys.iter()
                .map(|k| scalar(obj.get(k).unwrap_or(&Value::Null)))
                .collect()
        })
        .collect();

    let mut consts: Vec<(String, String)> = Vec::new();
    let mut var_idx: Vec<usize> = Vec::new();
    for (ci, key) in keys.iter().enumerate() {
        let first = &rows[0][ci];
        if rows.iter().all(|r| &r[ci] == first) {
            consts.push((key.clone(), first.clone()));
        } else {
            var_idx.push(ci);
        }
    }

    let mut extra: Vec<(String, String)> = Vec::new();
    let mut seen: BTreeSet<String> = BTreeSet::new();
    for item in arr {
        if let Some(obj) = item.as_object() {
            for (k, v) in obj {
                if !keys.contains(k) && seen.insert(k.clone()) {
                    extra.push((k.clone(), scalar(v)));
                }
            }
        }
    }

    let mut header = String::from("@csv");
    if !consts.is_empty() {
        let parts: Vec<String> =
            consts.iter().map(|(k, v)| format!("{k}={}", csv_field(v))).collect();
        header.push_str(&format!(" const({})", parts.join(",")));
    }
    let cols: Vec<String> = var_idx.iter().map(|&ci| csv_field(&keys[ci])).collect();
    header.push_str(&format!(" cols={}", cols.join(",")));
    if !extra.is_empty() {
        let parts: Vec<String> =
            extra.iter().map(|(k, v)| format!("{k}={}", csv_field(v))).collect();
        header.push_str(&format!(" extra({})", parts.join(",")));
    }

    let mut lines = vec![header];
    for r in &rows {
        let cells: Vec<String> = var_idx.iter().map(|&ci| csv_field(&r[ci])).collect();
        lines.push(cells.join(","));
    }
    Ok(Some(lines.join("\n")))
}

#[pymodule]
fn sensei_core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(csv_schema, m)?)?;
    Ok(())
}
