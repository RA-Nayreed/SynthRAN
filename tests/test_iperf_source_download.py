from synthran.research.iperf_toolchain import _BUILD_SCRIPT, _locked_spec


def test_locked_iperf_source_download_uses_explicit_user_agent() -> None:
    assert "urllib.request.Request(" in _BUILD_SCRIPT
    assert '"User-Agent": "SynthRAN/iperf-source-fetch"' in _BUILD_SCRIPT


def test_locked_iperf_source_artifact_stays_pinned() -> None:
    spec = _locked_spec()
    assert spec.version == "3.21"
    assert spec.url == "https://downloads.es.net/pub/iperf/iperf-3.21.tar.gz"
    assert spec.sha256 == (
        "sha256:656e4405ebd620121de7ceca3eaf43a88f79ea1b857d041a6a0b1314801acdd8"
    )
