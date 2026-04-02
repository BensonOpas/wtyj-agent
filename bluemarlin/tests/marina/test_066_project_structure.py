"""Brief 066 — verify project reorganization."""
import os
import sys

# conftest.py handles sys.path
_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..'))

def test_agents_marina_directory_exists():
    assert os.path.isdir(os.path.join(_ROOT, 'agents', 'marina'))

def test_shared_directory_exists():
    assert os.path.isdir(os.path.join(_ROOT, 'shared'))

def test_data_directory_exists():
    assert os.path.isdir(os.path.join(_ROOT, 'data'))

def test_src_directory_does_not_exist():
    assert not os.path.isdir(os.path.join(_ROOT, 'src'))

def test_marina_source_files_exist():
    marina_dir = os.path.join(_ROOT, 'agents', 'marina')
    expected = ['email_poller.py', 'marina_agent.py', 'gws_calendar.py',
                'sheets_writer.py', 'payment_stub.py', 'format_sheets.py',
                '__init__.py']
    for f in expected:
        assert os.path.isfile(os.path.join(marina_dir, f)), f"Missing: agents/marina/{f}"

def test_shared_source_files_exist():
    shared_dir = os.path.join(_ROOT, 'shared')
    expected = ['config_loader.py', 'bm_logger.py', 'state_registry.py', '__init__.py']
    for f in expected:
        assert os.path.isfile(os.path.join(shared_dir, f)), f"Missing: shared/{f}"

def test_config_loader_path_resolves():
    from shared import config_loader
    assert os.path.isfile(config_loader._CONFIG_PATH), \
        f"config_loader._CONFIG_PATH does not exist: {config_loader._CONFIG_PATH}"

def test_bm_logger_path_resolves():
    from shared import bm_logger
    log_dir = os.path.dirname(bm_logger.LOG_PATH)
    assert os.path.isdir(log_dir), f"Log directory does not exist: {log_dir}"

def test_state_registry_db_path():
    """Check the source code default, not runtime value (other tests may patch DB_PATH)."""
    sr_path = os.path.join(_ROOT, 'shared', 'state_registry.py')
    with open(sr_path) as f:
        src = f.read()
    assert '"data"' in src or "'data'" in src, \
        "state_registry.py DB_PATH should reference data/ directory in source"
    assert 'state_registry.db' in src, \
        "state_registry.py should define state_registry.db filename"

def test_imports_from_agents_marina():
    from agents.marina import email_poller
    from agents.marina import marina_agent
    from agents.marina import gws_calendar
    from agents.marina import sheets_writer
    from agents.marina import payment_stub
    assert hasattr(email_poller, 'main')
    assert hasattr(marina_agent, 'process_message')

def test_imports_from_shared():
    from shared import config_loader
    from shared import bm_logger
    from shared import state_registry
    assert hasattr(config_loader, 'get_services')
    assert hasattr(bm_logger, 'log')
    assert hasattr(state_registry, 'DB_PATH')

def test_no_sys_path_insert_in_tests():
    """No test file should have sys.path.insert -- conftest.py handles it."""
    test_dir = os.path.dirname(__file__)
    violations = []
    for fname in os.listdir(test_dir):
        if fname.startswith('test_') and fname.endswith('.py') and fname != 'test_066_project_structure.py':
            with open(os.path.join(test_dir, fname)) as f:
                content = f.read()
            if 'sys.path.insert' in content:
                violations.append(fname)
    assert not violations, f"Files still have sys.path.insert: {violations}"
