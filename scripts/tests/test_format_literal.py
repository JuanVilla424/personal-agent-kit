"""format_yml: el contenido shell de los bloques literales (run: |) no se toca."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from format_yml.main import format_yml_file  # noqa: E402


def test_run_block_bash_survives_formatting(tmp_path):
    wf = tmp_path / "workflow.yml"
    wf.write_text(
        "---\n"
        "jobs:\n"
        "  promote:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - name: Determine Branch\n"
        "        run: |\n"
        "          CURRENT_BRANCH=${GITHUB_REF#refs/heads/}\n"
        '          if [ "$CURRENT_BRANCH" = "dev" ]; then\n'
        '            NEXT_BRANCH="test"\n'
        "          fi\n"
        '          echo "next_branch=$NEXT_BRANCH" >> $GITHUB_OUTPUT\n'
        "      - name: Arrow Check\n"
        "        run: |\n"
        '          if [[ "$COMMIT_MSG" == *"→"* && "$COMMIT_MSG" == *"Bump version:"* ]]; then\n'
        '            echo "contains_arrow=true" >> $GITHUB_OUTPUT\n'
        "          fi\n"
        "      - name: Notes\n"
        "        run: |\n"
        '          [ -n "$FEATURES" ] && BODY="${BODY}x"\n'
        "      - name: Plain yaml list that MUST be tightened\n"
        "        run: echo [ 42 ]\n"
    )
    format_yml_file(str(wf))
    out = wf.read_text()
    assert 'if [ "$CURRENT_BRANCH" = "dev" ]; then' in out
    assert 'if [[ "$COMMIT_MSG" == *"→"* && "$COMMIT_MSG" == *"Bump version:"* ]]; then' in out
    assert '[ -n "$FEATURES" ] && BODY=' in out
    # el yaml real fuera de bloques literales sí se aprieta
    assert "run: echo [42]" in out
