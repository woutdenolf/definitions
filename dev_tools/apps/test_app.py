from ..nxdl import iter_definitions
from ..nxdl import validate_definition


def nxtest_args(parser):

    pass


def nxtest_exec(args):
    for path in iter_definitions():
        print(path, end="", flush=False)
        validate_definition(path)
        print(" [passed]")
