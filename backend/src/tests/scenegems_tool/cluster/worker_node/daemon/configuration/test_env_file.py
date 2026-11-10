import pytest

from scenegems_tool.cluster.worker_node.daemon.configuration.env_file import EnvFileError, parse_env_text, read_env_file


def test_keys_values_comments_and_quotes():
    text = "# worker node\n\nA=1\nexport B = two words \nC='quoted # not a comment'\nD=\"x\"\nE=\nF=a=b\n"
    assert parse_env_text(text) == {"A": "1", "B": "two words", "C": "quoted # not a comment", "D": "x", "E": "", "F": "a=b"}


def test_a_later_line_wins():
    assert parse_env_text("A=1\nA=2\n") == {"A": "2"}


@pytest.mark.parametrize("line", ["JUST_A_KEY", "1A=x", "A B=x", "=x"])
def test_malformed_lines_name_their_number(line):
    with pytest.raises(EnvFileError, match="line 2"):
        parse_env_text(f"A=1\n{line}\n", "worker_node.env")


def test_read_env_file_handles_crlf(tmp_path):
    path = tmp_path / ".env"
    path.write_bytes(b"A=1\r\nB=2\r\n")
    assert read_env_file(path) == {"A": "1", "B": "2"}
