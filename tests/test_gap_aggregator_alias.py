from knowledge_gap_aggregator.alias import is_known, normalize


def test_normalize_lowercases_and_strips():
    assert normalize("  CLIP Vision Encoder ") == "clip vision encoder"

def test_normalize_collapses_whitespace():
    assert normalize("Mel   Spectrogram") == "mel spectrogram"

def test_normalize_strips_trailing_punctuation():
    assert normalize("Transformer.") == "transformer"
    assert normalize("ViT,") == "vit"

def test_normalize_handles_hyphens_as_spaces():
    assert normalize("wav2vec-2.0") == "wav2vec 2.0"

def test_is_known_exact_alias():
    kb = {"aliases": {"transformer": ["transformer", "transformers"]}}
    assert is_known("Transformer", kb) is True
    assert is_known("transformers", kb) is True

def test_is_known_normalized_match():
    kb = {"aliases": {"mel spectrogram": ["mel spectrogram"]}}
    assert is_known("Mel  Spectrogram.", kb) is True

def test_is_known_returns_false_for_unknown():
    kb = {"aliases": {"transformer": ["transformer"]}}
    assert is_known("CLIP vision encoder", kb) is False

def test_is_known_empty_kb():
    assert is_known("anything", {"aliases": {}}) is False
