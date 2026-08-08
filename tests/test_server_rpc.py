from pipal.server_config import ServerSettings
from pipal.server_rpc import PiRpcClient


def test_rpc_environment_disables_unsolicited_greeting(tmp_path):
    client = PiRpcClient(
        settings=ServerSettings(
            auth_token=None,
            cors_origins=(),
            pipal_extensions_dir=None,
            pi_bin="pi",
        ),
        agent_dir=tmp_path,
        topic_name="release-smoke",
    )

    env = client._build_env()

    assert env["PIPAL_AGENT_DIR"] == str(tmp_path)
    assert env["PIPAL_TOPIC"] == "release-smoke"
    assert env["PIPAL_DISABLE_AUTOGREET"] == "1"
