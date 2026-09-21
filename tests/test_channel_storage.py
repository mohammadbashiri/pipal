from pipal.channel_storage import channel_topic_dir, create_channel, list_channels, load_channel


def test_channel_is_a_durable_shared_room(tmp_path, monkeypatch):
    monkeypatch.setenv("PIPAL_HOME", str(tmp_path))

    channel = create_channel(
        "product",
        [("ada", "Researcher"), ("raven", "Reviewer")],
        owner="Mo",
    )

    assert channel["name"] == "product"
    assert [member["agent"] for member in channel["members"]] == ["ada", "raven"]
    assert load_channel("product")["owner"] == "Mo"
    assert [item["name"] for item in list_channels()] == ["product"]
    topic = channel_topic_dir("product", "launch")
    assert (topic / "transcript.jsonl").is_file()
    assert (topic / "members").is_dir()
