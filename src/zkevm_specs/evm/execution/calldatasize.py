from ..instruction import Instruction, Transition
from ..table import CallContextFieldTag
from ..opcode import Opcode
from ...util.param import N_BYTES_U64


def calldatasize(instruction: Instruction):
    opcode = instruction.opcode_lookup(True)
    instruction.constrain_equal(opcode, Opcode.CALLDATASIZE)

    # check [rw_table, call_context] table for call data length and compare
    # against stack top after push.
    instruction.constrain_equal(
        instruction.int_to_rlc(
            instruction.call_context_lookup(CallContextFieldTag.CallDataLength),
            N_BYTES_U64,
        ),
        instruction.stack_push(),
    )

    instruction.step_state_transition_in_same_context(
        opcode,
        rw_counter=Transition.delta(2),
        program_counter=Transition.delta(1),
        stack_pointer=Transition.delta(-1),
    )

