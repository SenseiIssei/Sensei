"""Tests for output-token shaping and its holdout measurement.

Two things are being protected here, and the second matters more.

The first is mechanical: the instruction must reach the model without touching
the system prompt, because the system prompt is the cached prefix and
`CacheAligner` exists to keep it byte-identical.

The second is the honesty of the number. This feature exists to answer "did that
actually make answers shorter", and the failure mode is not a crash — it is a
confident percentage computed from eleven requests, which is worse than no
number at all because people quote it.
"""

from __future__ import annotations

import random
from pathlib import Path
from typing import Any, ClassVar

import pytest

from sensei import output_shaping
from sensei import savings as savings_mod
from sensei.savings import SavingsLedger


@pytest.fixture(autouse=True)
def shaper_on(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(output_shaping.settings, "output_shaper", True)
    monkeypatch.setattr(output_shaping.settings, "output_holdout", 0.1)
    monkeypatch.setattr(output_shaping.settings, "output_shaper_instruction", "")


# ── Where the instruction goes ──────────────────────────────────────────────


class TestShaping:
    def test_appends_to_the_last_user_message(self) -> None:
        out = output_shaping.shape_messages(
            [
                {"role": "system", "content": "You are helpful."},
                {"role": "user", "content": "first"},
                {"role": "assistant", "content": "ok"},
                {"role": "user", "content": "second"},
            ]
        )
        assert out[3]["content"].startswith("second")
        assert output_shaping.DEFAULT_INSTRUCTION in out[3]["content"]

    def test_never_touches_the_system_prompt(self) -> None:
        """The system prompt is the cached prefix. Appending to it would
        invalidate the provider's cache on every single request, which costs
        more in latency than this feature can save."""
        original = "You are helpful."
        out = output_shaping.shape_messages(
            [{"role": "system", "content": original}, {"role": "user", "content": "hi"}]
        )
        assert out[0]["content"] == original

    def test_earlier_turns_stay_byte_identical(self) -> None:
        """Only the last user message changes, so everything before it is still
        eligible for prefix caching."""
        messages = [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "answer"},
            {"role": "user", "content": "second"},
        ]
        out = output_shaping.shape_messages(messages)
        assert out[0] == messages[0]
        assert out[1] == messages[1]

    def test_does_not_mutate_the_caller(self) -> None:
        """The uncompressed originals go into the CCR store; mutating them
        would make a retrieved 'original' contain an instruction the user never
        wrote."""
        messages = [{"role": "user", "content": "hi"}]
        output_shaping.shape_messages(messages)
        assert messages == [{"role": "user", "content": "hi"}]

    def test_handles_anthropic_content_blocks(self) -> None:
        """Content can be a list of blocks, one of which might be an image."""
        out = output_shaping.shape_messages(
            [{"role": "user", "content": [{"type": "text", "text": "look at this"}]}]
        )
        blocks = out[0]["content"]
        assert len(blocks) == 2
        assert blocks[0] == {"type": "text", "text": "look at this"}
        assert blocks[1]["text"] == output_shaping.DEFAULT_INSTRUCTION

    def test_a_conversation_with_no_user_turn_is_left_alone(self) -> None:
        messages = [{"role": "system", "content": "x"}]
        assert output_shaping.shape_messages(messages) == messages

    def test_a_custom_instruction_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(output_shaping.settings, "output_shaper_instruction", "Be terse.")
        out = output_shaping.shape_messages([{"role": "user", "content": "hi"}])
        assert out[0]["content"].endswith("Be terse.")


class TestAssignment:
    def test_nothing_is_shaped_when_the_feature_is_off(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(output_shaping.settings, "output_shaper", False)
        assert not any(output_shaping.assign() for _ in range(50))

    def test_holdout_fraction_is_roughly_honoured(self) -> None:
        rng = random.Random(4)
        shaped = sum(output_shaping.assign(rng) for _ in range(4000))
        # 10% holdout -> ~90% shaped. Wide bounds: this asserts the wiring is
        # right, not that Python's RNG works.
        assert 0.86 < shaped / 4000 < 0.94

    def test_a_zero_holdout_shapes_everything(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Setting the holdout to 0 turns off the *measurement*, not the
        shaping — which is a defensible choice, but it must not silently turn
        off the feature too."""
        monkeypatch.setattr(output_shaping.settings, "output_holdout", 0.0)
        assert all(output_shaping.assign() for _ in range(50))


class TestInstructionIsCharged:
    """The instruction is real input tokens and has to be counted as such.

    Found by running it: both arms reported identical `prompt_tokens_after`,
    because shaping happens after compression and the savings dict had already
    been computed. Left alone, switching the shaper on would have quietly
    improved the reported input savings — a feature flattering its own
    scoreboard.
    """

    BASE: ClassVar[dict[str, Any]] = {
        "compression_enabled": True,
        "prompt_tokens_before": 1000,
        "prompt_tokens_after": 200,
        "tokens_saved": 800,
        "compression_ratio": 0.2,
    }

    def test_the_instruction_costs_input_tokens(self) -> None:
        out = output_shaping.account_for_instruction(self.BASE)
        cost = out["shaper_instruction_tokens"]
        assert cost > 0
        assert out["prompt_tokens_after"] == 200 + cost
        assert out["tokens_saved"] == 800 - cost

    def test_the_ratio_is_recomputed(self) -> None:
        out = output_shaping.account_for_instruction(self.BASE)
        assert out["compression_ratio"] == round(out["prompt_tokens_after"] / 1000, 4)
        assert out["compression_ratio"] > self.BASE["compression_ratio"]

    def test_the_original_dict_is_not_mutated(self) -> None:
        before = dict(self.BASE)
        output_shaping.account_for_instruction(self.BASE)
        assert before == self.BASE

    def test_a_longer_instruction_costs_more(self, monkeypatch: pytest.MonkeyPatch) -> None:
        cheap = output_shaping.account_for_instruction(self.BASE)["shaper_instruction_tokens"]
        monkeypatch.setattr(
            output_shaping.settings, "output_shaper_instruction", "Be terse. " * 200
        )
        dear = output_shaping.account_for_instruction(self.BASE)["shaper_instruction_tokens"]
        assert dear > cheap * 5


# ── The number ──────────────────────────────────────────────────────────────


class TestEffect:
    def test_refuses_to_report_on_a_small_sample(self) -> None:
        """The failure this prevents: '31% shorter' computed from eleven
        requests, quoted forever after."""
        result = output_shaping.effect([100] * 11, [200] * 11)
        assert result["verdict"] == "not enough data yet"
        assert "difference_tokens" not in result
        assert "percent" not in result

    def test_says_how_many_more_are_needed(self) -> None:
        result = output_shaping.effect([100] * 25, [200] * 40)
        assert "5 more request" in result["detail"]

    def test_reports_a_clear_effect_with_an_interval(self) -> None:
        rng = random.Random(1)
        control = [int(rng.gauss(400, 40)) for _ in range(200)]
        shaped = [int(rng.gauss(280, 30)) for _ in range(200)]

        result = output_shaping.effect(shaped, control)
        assert result["verdict"] == "shorter answers"
        low, high = result["confidence_interval_95"]
        assert low > 0
        assert low < result["difference_tokens"] < high
        assert 25 < result["percent"] < 35

    def test_noise_is_reported_as_no_difference(self) -> None:
        """Two samples from the same distribution must not produce a claim.

        Without the interval, the point estimate here would be some non-zero
        number and would read as an effect.
        """
        rng = random.Random(2)
        a = [int(rng.gauss(400, 60)) for _ in range(300)]
        b = [int(rng.gauss(400, 60)) for _ in range(300)]

        result = output_shaping.effect(a, b)
        assert result["verdict"] == "no measurable difference"
        low, high = result["confidence_interval_95"]
        assert low < 0 < high

    def test_a_harmful_change_is_reported_as_such(self) -> None:
        """If the instruction makes answers *longer*, that has to show up."""
        rng = random.Random(3)
        control = [int(rng.gauss(300, 30)) for _ in range(200)]
        shaped = [int(rng.gauss(420, 30)) for _ in range(200)]

        assert output_shaping.effect(shaped, control)["verdict"] == "longer answers"


# ── The ledger side ─────────────────────────────────────────────────────────


class TestLedgerArms:
    @pytest.fixture
    def ledger(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SavingsLedger:
        monkeypatch.setattr(savings_mod.settings, "savings_db", str(tmp_path / "s.db"))
        monkeypatch.setattr(savings_mod.settings, "savings_persist", True)
        return SavingsLedger()

    def test_arms_are_separated(self, ledger: SavingsLedger) -> None:
        for _ in range(3):
            ledger.append({}, shaped=1, output_tokens=100)
        for _ in range(2):
            ledger.append({}, shaped=0, output_tokens=250)

        shaped, control = ledger.output_arms()
        assert shaped == [100, 100, 100]
        assert control == [250, 250]

    def test_rows_from_before_the_experiment_are_excluded(self, ledger: SavingsLedger) -> None:
        """`shaped = -1` means "not part of the experiment", which is a
        different fact from "in the control arm". Merging them would bias the
        comparison with history collected before the feature existed."""
        ledger.append({}, output_tokens=999)  # default shaped=-1
        ledger.append({}, shaped=0, output_tokens=250)

        shaped, control = ledger.output_arms()
        assert shaped == []
        assert control == [250]

    def test_responses_with_no_usage_block_are_excluded(self, ledger: SavingsLedger) -> None:
        """Streaming replies never report usage here. Counting them as zero
        would drag both arms down and shrink a real effect."""
        ledger.append({}, shaped=1, output_tokens=0)
        ledger.append({}, shaped=1, output_tokens=120)

        shaped, _ = ledger.output_arms()
        assert shaped == [120]

    def test_output_tokens_can_be_filled_in_afterwards(self, ledger: SavingsLedger) -> None:
        """The count is not known when the request is recorded."""
        row = ledger.append({}, shaped=1, output_tokens=0)
        assert row is not None
        ledger.set_output_tokens(row, 321)

        shaped, _ = ledger.output_arms()
        assert shaped == [321]

    def test_an_old_ledger_gains_the_new_columns(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A user's ledger is their own history; changing the schema must not
        require throwing it away."""
        import sqlite3

        db = tmp_path / "old.db"
        conn = sqlite3.connect(db)
        conn.executescript(
            "CREATE TABLE events (ts REAL NOT NULL, tool TEXT DEFAULT '',"
            " provider TEXT DEFAULT '', model TEXT DEFAULT '', before INTEGER DEFAULT 0,"
            " after INTEGER DEFAULT 0, saved INTEGER DEFAULT 0, blocks INTEGER DEFAULT 0);"
        )
        conn.execute("INSERT INTO events (ts, saved, before, after) VALUES (1, 500, 1000, 500)")
        conn.commit()
        conn.close()

        monkeypatch.setattr(savings_mod.settings, "savings_db", str(db))
        monkeypatch.setattr(savings_mod.settings, "savings_persist", True)

        ledger = SavingsLedger()
        assert ledger.totals()["tokens_saved"] == 500  # the old row survived
        ledger.append({}, shaped=1, output_tokens=42)
        assert ledger.output_arms()[0] == [42]
