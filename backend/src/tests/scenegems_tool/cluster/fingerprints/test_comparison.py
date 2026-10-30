from scenegems_tool.cluster.fingerprints.comparison import FingerprintMismatch, by_repository, find_mismatches, fingerprints_of, repositories, with_legacy_names


def test_matching_fingerprints_have_no_mismatch():
    assert find_mismatches({"a": "1", "b": "2"}, {"a": "1"}) == []


def test_different_fingerprint_is_reported_with_both_values():
    assert find_mismatches({"a": "old"}, {"a": "new"}) == [FingerprintMismatch("a", "new", "old")]


def test_missing_image_is_reported_as_missing():
    (mismatch,) = find_mismatches({}, {"a": "1"})
    assert mismatch.missing and mismatch.actual is None


def test_images_not_required_are_ignored():
    assert find_mismatches({"extra": "x"}, {}) == []


def test_images_compare_by_repository_whatever_their_tags():
    assert find_mismatches({"a:abc123": "1"}, {"a:latest": "1"}) == []
    assert find_mismatches({"a:abc123": "2"}, {"a:latest": "1"}) == [FingerprintMismatch("a", "1", "2")]


def test_by_repository_drops_the_tag_and_prefers_the_named_one():
    assert by_repository({"a:latest": "1", "registry:5000/b:v2": "2", "c": "3"}) == {"a": "1", "registry:5000/b": "2", "c": "3"}
    both = {"a:latest": "old", "a:abc123": "new"}
    assert by_repository(both, "latest") == {"a": "old"} and by_repository(both, "abc123") == {"a": "new"}
    assert by_repository(both) == {"a": "new"}, "without a preferred tag the first name wins"


def test_repositories_are_distinct_and_sorted():
    assert repositories(["b:latest", "a:x", "b:y"]) == ["a", "b"]


def test_the_fingerprints_of_images_hold_under_another_tag():
    pinned = {"a:latest": "1", "b:latest": "2"}  # a campaign pinned before release tags
    assert fingerprints_of(["a:abc123", "c:abc123"], pinned) == {"a": "1"}
    assert fingerprints_of(["a:abc123"], {"a": "1"}) == {"a": "1"}


def test_legacy_names_let_an_old_job_match_a_node_by_repository():
    node = with_legacy_names({"a": "1"})
    assert node == {"a": "1", "a:latest": "1"}
    old_job = {"a:latest": "1"}
    assert old_job.items() <= node.items() and {"a": "1"}.items() <= node.items()
