import pytest
from virea_sentiavatar.planner import LocalPlanner


@pytest.mark.parametrize(
    "url",
    [
        "https://remote.example",
        "http://127.0.0.1/path",
        "file:///model",
        "http://name@127.0.0.1:8084",
    ],
)
def test_local_planner_only_accepts_a_loopback_origin(url):
    with pytest.raises(Exception, match="loopback"):
        LocalPlanner(url)


def test_local_planner_uses_native_token_ids_in_both_directions(monkeypatch):
    class Tokenizer:
        def encode(self, prompt):
            assert prompt == "native prompt"
            return [12, 208862]

        def decode(self, tokens, skip_special_tokens):
            assert tokens == [208862, 151645] and not skip_special_tokens
            return "[res_1_0]<|im_end|>"

    def request(self, path, payload=None):
        if path == "/v1/models":
            return {"data": [{"id": "sentiavatar-planner"}]}
        assert payload["prompt"] == [12, 208862]
        assert payload["return_tokens"] and payload["repeat_penalty"] == 1
        return {"tokens": [208862, 151645], "stop_type": "eos"}

    monkeypatch.setattr(LocalPlanner, "_request", request)
    assert (
        LocalPlanner("http://127.0.0.1:8084")
        .generate(
            Tokenizer(),
            "native prompt",
            temperature=0.5,
            top_p=0.7,
            max_new_tokens=1024,
            seed=42,
        )
        .startswith("[res_1_0]")
    )
