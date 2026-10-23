"""Drive the Streamlit app headlessly with AppTest: every bundled problem, both objectives."""
import pytest
from streamlit.testing.v1 import AppTest

from linebalance.io import bundled_examples

APP = str(__import__("pathlib").Path(__file__).resolve().parent.parent / "app.py")
EXAMPLES = bundled_examples()


@pytest.mark.parametrize("key", list(EXAMPLES))
@pytest.mark.parametrize("mode", ["SALBP-1: minimise stations", "SALBP-2: minimise cycle time"])
def test_app_solves_every_bundled_problem(key, mode):
    at = AppTest.from_file(APP, default_timeout=120)
    at.run()
    at.selectbox(key="example").set_value(key).run()
    at.radio(key="mode").set_value(mode).run()
    assert not at.exception
    at.button(key="solve").click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert not at.error, [e.value for e in at.error]
    assert any("Method comparison" in s.value for s in at.subheader)
    # cycle through every method's detail view
    for name in at.radio(key="detail").options:
        at.radio(key="detail").set_value(name).run()
        assert not at.exception
