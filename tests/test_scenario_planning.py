import os
import tempfile
import pytest
from adapters.duckdb_repo import DuckDBRepo
from services.scenario_service import (
    save_scenario, list_scenarios, load_scenario, delete_scenario,
)


@pytest.fixture
def repo_tmp():
    d = tempfile.mkdtemp()
    p = os.path.join(d, "test.db")
    r = DuckDBRepo(p)
    yield r
    r.close()


def test_save_and_load(repo_tmp):
    save_scenario(repo_tmp, "baseline",
                  {"rayon_km": 40, "cout_cit": 150},
                  notes="default")
    s = load_scenario(repo_tmp, "baseline")
    assert s is not None
    assert s["params"]["rayon_km"] == 40
    assert "snapshot" in s


def test_list_and_delete(repo_tmp):
    save_scenario(repo_tmp, "A", {"rayon_km": 40})
    save_scenario(repo_tmp, "B", {"rayon_km": 60})
    df = list_scenarios(repo_tmp)
    assert len(df) == 2
    delete_scenario(repo_tmp, "A")
    assert len(list_scenarios(repo_tmp)) == 1


def test_overwrite(repo_tmp):
    save_scenario(repo_tmp, "X", {"rayon_km": 40})
    save_scenario(repo_tmp, "X", {"rayon_km": 60})
    s = load_scenario(repo_tmp, "X")
    assert s["params"]["rayon_km"] == 60
