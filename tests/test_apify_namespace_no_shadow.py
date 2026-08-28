"""Regression test: Ensure official apify SDK is not shadowed by local package."""


def test_official_apify_sdk_importable():
    from apify import Actor
    assert Actor is not None
    assert hasattr(Actor, "charge")
    assert hasattr(Actor, "push_data")


def test_apify_actor_wrapper_importable():
    import apify_actor
    from apify_actor import input_to_config, ApifyDatasetSink
    import apify_actor.main
    assert input_to_config is not None
    assert ApifyDatasetSink is not None
    assert apify_actor.main is not None
