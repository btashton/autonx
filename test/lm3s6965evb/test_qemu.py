
import pytest

from labgrid import Environment
from labgrid.consoleloggingreporter import ConsoleLoggingReporter
from labgrid.protocol import CommandProtocol
from autonx import NSHStrategy

import logging
import os
import re

ConsoleLoggingReporter.start(".")
logging.getLogger().setLevel(logging.DEBUG)

@pytest.fixture(scope='session')
def target():
    return Environment(os.path.join(os.path.dirname(__file__), "config.yaml")).get_target('lm3s6965evb-flat')

@pytest.fixture(scope='session')
def strategy(target):
    return target.get_driver(NSHStrategy)

@pytest.fixture(scope='function')
def shell_command(target, strategy):
    strategy.transition('shell')
    return target.get_active_driver(CommandProtocol)

def test_echo(shell_command):
    result = shell_command.run_check('echo OK')
    assert 'OK' in result

def test_version(shell_command):
    result = shell_command.run_check('cat /proc/version')
    assert re.match(r'NuttX version \d+\.\d+\.\d+.*', result[0])
