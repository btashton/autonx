import attr
import logging
import re
import subprocess
import datetime

from labgrid.driver.common import Driver
from labgrid.driver.exception import ExecutionError
from labgrid.driver.commandmixin import CommandMixin
from labgrid.driver.externalconsoledriver import ExternalConsoleDriver
from labgrid.factory import target_factory
from labgrid.protocol import PowerProtocol, CommandProtocol, ConsoleProtocol
from labgrid.step import step
from labgrid.strategy.shellstrategy import ShellStrategy


@target_factory.reg_driver
@attr.s(eq=False)
class NSHDriver(CommandMixin, Driver, CommandProtocol):
    """
    Args:
        prompt (str): The default NSH Prompt
        init_commands (Tuple[str]): a tuple of commands to run after unlock
        login_timeout (int): optional, timeout for login prompt detection,
        boot_expression (str): string to search for on NSH start
    """

    bindings = {
        "console": ConsoleProtocol,
    }
    login_timeout = attr.ib(default=60, validator=attr.validators.instance_of(int))
    boot_expression = attr.ib(
        default="NuttShell \(NSH\) NuttX", validator=attr.validators.instance_of(str)
    )
    prompt = attr.ib(default="nsh> ", validator=attr.validators.instance_of(str))
    init_commands = attr.ib(default=attr.Factory(tuple), converter=tuple)

    def __attrs_post_init__(self):
        super().__attrs_post_init__()
        self.re_vt100 = re.compile(r"(\x1b\[|\x9b)[^@-_a-z]*[@-_a-z]|\x1b[@-_a-z]")
        self.logger = logging.getLogger("{}:{}".format(self, self.target))
        self._status = 0

    @step()
    def _await_prompt(self):
        """
        Await autoboot_expression.
        """

        # wait for boot expression.
        self.console.expect(self.boot_expression, timeout=self.login_timeout)
        self._status = 1

        # wait until NuttX has reached it's prompt
        self.console.expect(self.prompt)
        for command in self.init_commands:  # pylint: disable=not-an-iterable
            out, _, err = self._run(command)
            if err != 0:
                self.logger.error("Unexpected error (%d): %s", err, "\n".join(out))

    def _run(
        self,
        cmd: str,
        *,
        timeout: int = 30,
        codec: str = "utf-8",
        decodeerrors: str = "strict"
    ):  # pylint: disable=unused-argument,line-too-long
        """
        If NSH is in Command-Line mode: Run command cmd and return it's
        output. We really do not have a great way to use echo markers
        with this shell or return the correct status code.

        Arguments:
        cmd - Command to run
        """
        # Check if NSH is in command line mode
        if self._status != 1:
            return None

        cmp_command = "{cmd}".format(cmd=cmd)

        self.console.sendline(cmp_command)
        _, before, _, _ = self.console.expect(self.prompt, timeout=timeout)

        data = (
            self.re_vt100.sub("", before.decode("utf-8"), count=1000000)
            .replace("\r", "")
            .split("\n")
        )
        data = data[1:-1]

        # We do not have a good way to look for an error code,
        # but this pattern usually means we at least hit an nsh error at least
        r_not_found = re.compile(r"nsh: .*: ")

        try:
            cmp_command = "{cmd}".format(cmd="echo $?")
            self.console.sendline(cmp_command)
            _, before, _, _ = self.console.expect(self.prompt, timeout=timeout)

            ret_data = (
                self.re_vt100.sub("", before.decode("utf-8"), count=1000000)
                .replace("\r", "")
                .split("\n")
            )
            return (data, [], int(ret_data[-2]))
        except:
            # We do not support $? for finding the return code
            pass

        if len(data) and r_not_found.match(data[-1]):
            rsp = (data, [], 255)

        return (data, [], -1)

    def on_activate(self):
        """Activate the NSHDriver
        This function checks for a prompt and awaits it if not already active
        """
        if self._status == 0:
            self._await_prompt()

    def on_deactivate(self):
        """Deactivate the NSHDriver
        Simply sets the internal status to 0
        """
        self._status = 0

    @Driver.check_active
    @step(args=["cmd"], result=True)
    def run(self, cmd, timeout=30.0, codec="utf-8", decodeerrors="strict"):
        return self._run(cmd, timeout=timeout, codec=codec, decodeerrors=decodeerrors)

    @step()
    def get_status(self):
        """Returns the status of the shell-driver.
        0 means not connected/found, 1 means shell
        """
        return self._status


@target_factory.reg_driver
@attr.s(eq=False)
class NSHStrategy(ShellStrategy):
    """NSHStrategy - Strategy to switch to shell"""

    bindings = {
        "power": PowerProtocol,
        "shell": NSHDriver,
    }


@target_factory.reg_driver
@attr.s(eq=False)
class SimConsoleDriver(ExternalConsoleDriver):
    def _read(self, size: int = 1024, timeout: int = 0):
        """
        Reads 'size' bytes from the simulator console
        Keyword Arguments:
        size -- amount of bytes to read, defaults to 1024
        """
        if self._child.poll() is not None:
            raise ExecutionError("child has vanished")

        pending = self._child.stdout.read(size)
        if pending is not None:
            return pending
        if self._poll.poll(timeout):
            res = self._child.stdout.read(size)
            if res is not None:
                return res

        return b""

    def close(self):
        """Stops the subprocess, does nothing if it is already closed"""
        # The simulation does not respond to term, so just kill
        self._child.kill()
        outs, errs = self._child.communicate()

        if outs:
            self.logger.info("child stdout while closing: %s", outs)
        if errs:
            self.logger.warning("child error while closing: %s", errs)
