//! Low-level Rust hot paths for Sensei compression.
//!
//! Optional accelerator: Python soft-imports `sensei_core` and uses it when
//! present, falling back to the pure-Python implementation otherwise. Output is
//! byte-compatible with `SmartCrusher._to_csv_schema` for the tested shapes.

use pyo3::prelude::*;
use regex::Regex;
use serde_json::Value;
use std::collections::BTreeSet;
use std::sync::OnceLock;

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

// ─── Log compressor (parity with Python sensei.compression.logcomp) ──────────

fn important_re() -> &'static Regex {
    static R: OnceLock<Regex> = OnceLock::new();
    R.get_or_init(|| {
        Regex::new(
            r"(?i)(error|fatal|critical|fail(?:ed|ure)?|warn(?:ing)?|exception|traceback|panic|assert|denied|refused|timeout|✗|✘|✖|fixme)",
        )
        .unwrap()
    })
}

fn summary_re() -> &'static Regex {
    static R: OnceLock<Regex> = OnceLock::new();
    R.get_or_init(|| {
        Regex::new(
            r"(?i)(\b\d+\s+(?:passed|failed|error|warning|skipped)\b|={3,}|-{3,}|\bbuild (?:succeeded|failed|success|complete)\b|\bdone\b|\bsummary\b)",
        )
        .unwrap()
    })
}

fn frame_re() -> &'static Regex {
    static R: OnceLock<Regex> = OnceLock::new();
    R.get_or_init(|| Regex::new(r#"^\s*(at |File ", "|in |\| |#\d+ |\.\.\. )"#).unwrap())
}

fn ts_re() -> &'static Regex {
    static R: OnceLock<Regex> = OnceLock::new();
    R.get_or_init(|| Regex::new(r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}\S*").unwrap())
}

fn hex_re() -> &'static Regex {
    static R: OnceLock<Regex> = OnceLock::new();
    R.get_or_init(|| Regex::new(r"\b0x[0-9a-fA-F]+\b").unwrap())
}

fn num_re() -> &'static Regex {
    static R: OnceLock<Regex> = OnceLock::new();
    R.get_or_init(|| Regex::new(r"\b\d+\b").unwrap())
}

fn normalize(line: &str) -> String {
    let s = ts_re().replace_all(line, "<ts>");
    let s = hex_re().replace_all(&s, "<hex>");
    let s = num_re().replace_all(&s, "<n>");
    s.trim().to_string()
}

fn collapse_repeats(lines: Vec<String>) -> String {
    let mut result: Vec<String> = Vec::new();
    let mut prev_norm: Option<String> = None;
    let mut count: usize = 0;
    for line in lines {
        let norm = normalize(&line);
        if Some(&norm) == prev_norm.as_ref() && !norm.trim().is_empty() {
            count += 1;
            continue;
        }
        if count > 1 {
            let last = result.len() - 1;
            result[last] = format!("{} (x{})", result[last], count);
        }
        result.push(line);
        prev_norm = Some(norm);
        count = 1;
    }
    if count > 1 {
        let last = result.len() - 1;
        result[last] = format!("{} (x{})", result[last], count);
    }
    result.join("\n")
}

fn do_compress_logs(text: &str, context_after: usize, head: usize, tail: usize) -> String {
    let lines: Vec<&str> = text.split('\n').collect();
    let n = lines.len();
    if n < 10 {
        return text.to_string();
    }
    let mut keep = vec![false; n];
    for i in 0..head.min(n) {
        keep[i] = true;
    }
    for i in n.saturating_sub(tail)..n {
        keep[i] = true;
    }
    for i in 0..n {
        if important_re().is_match(lines[i]) || summary_re().is_match(lines[i]) {
            keep[i] = true;
            let end = (i + 1 + context_after).min(n);
            for j in (i + 1)..end {
                if frame_re().is_match(lines[j]) || !lines[j].trim().is_empty() {
                    keep[j] = true;
                }
            }
        }
    }

    let mut out: Vec<String> = Vec::new();
    let mut i = 0;
    while i < n {
        if keep[i] {
            out.push(lines[i].to_string());
            i += 1;
        } else {
            let mut j = i;
            while j < n && !keep[j] {
                j += 1;
            }
            out.push(format!("… {} lines omitted …", j - i));
            i = j;
        }
    }
    collapse_repeats(out)
}

#[pyfunction]
#[pyo3(signature = (text, context_after=2, head=3, tail=3))]
fn compress_logs(text: &str, context_after: usize, head: usize, tail: usize) -> PyResult<String> {
    Ok(do_compress_logs(text, context_after, head, tail))
}

// ─── Text compressor (parity with Python sensei.compression.textcomp) ────────

const PHRASE_REPLACEMENTS: &[(&str, &str)] = &[
    ("in order to", "to"),
    ("due to the fact that", "because"),
    ("owing to the fact that", "because"),
    ("in spite of the fact that", "although"),
    ("despite the fact that", "although"),
    ("in the event that", "if"),
    ("for the purpose of", "for"),
    ("with regard to", "about"),
    ("with respect to", "about"),
    ("in relation to", "about"),
    ("a large number of", "many"),
    ("a great deal of", "much"),
    ("the vast majority of the", "most of the"),
    ("the majority of the", "most of the"),
    ("the vast majority of", "most"),
    ("the majority of", "most"),
    ("a majority of", "most"),
    ("a number of", "several"),
    ("all of the", "all the"),
    ("at this point in time", "now"),
    ("at the present time", "now"),
    ("in a timely manner", "promptly"),
    ("on a regular basis", "regularly"),
    ("has the ability to", "can"),
    ("have the ability to", "can"),
    ("is able to", "can"),
    ("are able to", "can"),
    ("is going to", "will"),
    ("are going to", "will"),
    ("make sure that", "ensure"),
    ("various different", "various"),
];

const FILLER: &[&str] = &[
    "basically", "actually", "really", "very", "quite", "simply", "literally", "essentially",
    "obviously", "clearly", "honestly", "totally", "definitely", "certainly", "arguably",
    "ultimately", "in fact", "of course", "as a matter of fact", "at the end of the day",
    "for all intents and purposes", "needless to say", "it goes without saying that",
    "generally speaking", "as you can see", "as we can see", "as you know",
    "it is very important to note that", "it is important to note that", "it is worth noting that",
    "it should be noted that", "please note that",
];

const BOILERPLATE: &[&str] = &[
    r"(?i)As mentioned (?:earlier|above|before)\s*,?\s*",
    r"(?i)As (?:stated|described) (?:earlier|above)\s*,?\s*",
    r"(?i)For more (?:information|details)\s*,?\s*see\s+\S+\s*",
    r"(?i)See (?:the )?(?:documentation|docs|README|guide) for more details\.?",
];

const MAX_PARAGRAPH: usize = 500;

struct TextEngine {
    replacements: Vec<(Regex, String)>,
    fillers: Vec<Regex>,
    boilerplate: Vec<Regex>,
    sp_tabs: Regex,
    around_nl: Regex,
    space_punct: Regex,
    repeated_comma: Regex,
    leading_punct: Regex,
    blanks: Regex,
    fix_caps: Regex,
}

fn text_engine() -> &'static TextEngine {
    static E: OnceLock<TextEngine> = OnceLock::new();
    E.get_or_init(|| {
        // Stable-sort phrases longest-first (matches Python's sorted(..., reverse=True)).
        let mut phrases: Vec<(&str, &str)> = PHRASE_REPLACEMENTS.to_vec();
        phrases.sort_by(|a, b| b.0.len().cmp(&a.0.len()));
        let replacements = phrases
            .into_iter()
            .map(|(k, v)| {
                (Regex::new(&format!(r"(?i)\b{}\b", regex::escape(k))).unwrap(), v.to_string())
            })
            .collect();

        let mut fillers_sorted: Vec<&str> = FILLER.to_vec();
        fillers_sorted.sort_by(|a, b| b.len().cmp(&a.len()));
        let fillers = fillers_sorted
            .into_iter()
            .map(|f| Regex::new(&format!(r"(?i)\s*,?\s*\b{}\b\s*,?\s*", regex::escape(f))).unwrap())
            .collect();

        let boilerplate = BOILERPLATE.iter().map(|p| Regex::new(p).unwrap()).collect();

        TextEngine {
            replacements,
            fillers,
            boilerplate,
            sp_tabs: Regex::new(r"[ \t]+").unwrap(),
            around_nl: Regex::new(r" *\n *").unwrap(),
            space_punct: Regex::new(r"\s+([,.;:!?])").unwrap(),
            repeated_comma: Regex::new(r"(?:,\s*){2,}").unwrap(),
            leading_punct: Regex::new(r"(?m)^[ \t]*[,;:][ \t]*").unwrap(),
            blanks: Regex::new(r"\n{3,}").unwrap(),
            fix_caps: Regex::new(r"(^\s*|[.!?]\s+|\n\s*)([a-z])").unwrap(),
        }
    })
}

fn split_sentences(line: &str) -> Vec<String> {
    // Mirror Python re.split(r"(?<=[.!?])\s+", line) without lookbehind.
    let chars: Vec<char> = line.chars().collect();
    let mut parts: Vec<String> = Vec::new();
    let mut start = 0usize;
    let mut i = 0usize;
    while i < chars.len() {
        if chars[i].is_whitespace() && i > 0 && matches!(chars[i - 1], '.' | '!' | '?') {
            parts.push(chars[start..i].iter().collect());
            let mut j = i;
            while j < chars.len() && chars[j].is_whitespace() {
                j += 1;
            }
            start = j;
            i = j;
        } else {
            i += 1;
        }
    }
    parts.push(chars[start..].iter().collect());
    parts
}

fn do_compress_text(input: &str) -> String {
    let e = text_engine();
    let mut text = input.to_string();

    for re in &e.boilerplate {
        text = re.replace_all(&text, "").into_owned();
    }
    for (re, repl) in &e.replacements {
        text = re.replace_all(&text, repl.as_str()).into_owned();
    }
    for re in &e.fillers {
        text = re.replace_all(&text, " ").into_owned();
    }

    // cleanup
    text = e.sp_tabs.replace_all(&text, " ").into_owned();
    text = e.around_nl.replace_all(&text, "\n").into_owned();
    text = e.space_punct.replace_all(&text, "${1}").into_owned();
    text = e.repeated_comma.replace_all(&text, ", ").into_owned();
    text = e.leading_punct.replace_all(&text, "").into_owned();

    // collapse blank lines
    text = e.blanks.replace_all(&text, "\n\n").into_owned();

    // dedupe lines
    {
        let mut seen: std::collections::HashSet<String> = std::collections::HashSet::new();
        let mut out: Vec<String> = Vec::new();
        for line in text.split('\n') {
            let stripped = line.trim();
            if !stripped.is_empty() && stripped.chars().count() > 20 && seen.contains(stripped) {
                continue;
            }
            if !stripped.is_empty() {
                seen.insert(stripped.to_string());
            }
            out.push(line.to_string());
        }
        text = out.join("\n");
    }

    // truncate paragraphs
    {
        let mut out: Vec<String> = Vec::new();
        for line in text.split('\n') {
            if line.chars().count() > MAX_PARAGRAPH {
                let sentences = split_sentences(line);
                if sentences.len() > 3 {
                    out.push(format!("{} […] {}", sentences[0], sentences[sentences.len() - 1]));
                } else {
                    let head: String = line.chars().take(MAX_PARAGRAPH).collect();
                    out.push(format!("{head}…"));
                }
            } else {
                out.push(line.to_string());
            }
        }
        text = out.join("\n");
    }

    // fix caps
    text = e
        .fix_caps
        .replace_all(&text, |caps: &regex::Captures| {
            format!("{}{}", &caps[1], caps[2].to_uppercase())
        })
        .into_owned();

    text.trim().to_string()
}

#[pyfunction]
fn compress_text(text: &str) -> PyResult<String> {
    Ok(do_compress_text(text))
}

#[pymodule]
fn sensei_core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(csv_schema, m)?)?;
    m.add_function(wrap_pyfunction!(compress_logs, m)?)?;
    m.add_function(wrap_pyfunction!(compress_text, m)?)?;
    Ok(())
}
