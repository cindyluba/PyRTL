"""
conditional contains the class for ConditionUpdate
"""

import core
import wire


# -----------------------------------------------------------------------
#    __   __        __    ___    __                  __
#   /  ` /  \ |\ | |  \ |  |  | /  \ |\ |  /\  |    /__`
#   \__, \__/ | \| |__/ |  |  | \__/ | \| /~~\ |___ .__/
#

class ConditionalUpdate(object):
    """ Manages the conditional update of registers based on a predicate.

    The management of conditional updates is expected to happen through
    the "with" blocks which will ensure that the region of execution for
    which the condition should apply is well defined.  It is easiest
    to see with an example:

    >   with ConditionalUpdate() as condition:
    >       r1 = Register()
    >       r2 = Register()
    >       with condition(a):
    >           r.next <<= x  # set when a is true
    >           with condition(b):
    >               r2.next <<= y  # set when a and b are true
    >       with condition(c):
    >           r.next <<= z  # set when a is false and c is true
    >           r2.next <<= z
    >       with condition.default:
    >           r.next <<= w  # a is false and c is false
    """

    depth = 0
    current = None

    def __init__(self, block=None):
        if self.depth != 0:
            raise core.PyrtlError('error, no nesting ConditionalUpdates')
        self.block = core.working_block(block)
        self.predicate_on_deck = None
        self.conditions_list_stack = [[]]
        self.register_predicate_map = {}  # map reg -> [(pred, rhs), ...]
        self.memblock_predicate_map = {}  # map mem -> [(pred, addr, data, enable), ...]

    def __enter__(self):
        if self.predicate_on_deck is None:
            if self.depth != 0:
                raise core.PyrtlError('error, you did something wrong with conditionals')
            ConditionalUpdate.current = self
            retval = self
        else:
            if self.depth <= 0:
                raise core.PyrtlError('error, need an enclosing ConditionalUpdate')
            self.conditions_list_stack[-1].append(self.predicate_on_deck)
            # push a new empty list on the stack for sub-conditions
            self.conditions_list_stack.append([])
            retval = None

        ConditionalUpdate.depth += 1
        self.predicate_on_deck = None
        return retval

    def __exit__(self, etype, evalue, etraceback):
        self.conditions_list_stack.pop()
        ConditionalUpdate.depth -= 1
        if self.depth == 0:
            self._register_finalize()
            # self._mem_finalize()
            ConditionalUpdate.current = None
        if self.depth < 0:
            raise core.PyrtlInternalError()

    def __call__(self, predicate):
        self.predicate_on_deck = predicate
        return self

    @property
    def default(self):
        self.predicate_on_deck = True
        return self

    def _register_init(self, reg):
        if self.depth == 1:
            self.register_predicate_map[reg] = []
        else:
            raise core.PyrtlError('error, cannot declare register in a condition')

    def _register_set(self, reg, rhs):
        p = self._current_select()
        self.register_predicate_map[reg].append((p, rhs))

    def _register_finalize(self):
        from helperfuncs import mux
        for reg in self.register_predicate_map:
            result = reg  # TODO: add check for default case, not feedback then
            # TODO: right now this is totally not optimzied, should use muxes
            # in conjuction with predicates to encode efficiently.
            regpredlist = self.register_predicate_map[reg]
            if regpredlist == []:
                raise core.PyrtlError('error, Register in ConditionalUpdate not assigned')
            for p, rhs in regpredlist:
                result = mux(p, truecase=rhs, falsecase=result)
            reg.reg_in = result
            net = core.LogicNet('r', None, args=(result,), dests=(reg,))
            self.block.add_net(net)

    def _memblock_init(self, memblock):
        raise NotImplementedError

    def _memblock_get(self, addr):
        raise NotImplementedError

    def _memblock_set(self, addr, data, enable):
        raise NotImplementedError

    def _memblock_finalize(self):
        raise NotImplementedError

    def _current_select(self):
        select = None

        # helper to create the conjuction of predicates
        def and_with_possible_none(a, b):
            assert(a is not None or b is not None)
            if a is None:
                return b
            if b is None:
                return a
            return a & b

        # for all conditions except the current children (which should be [])
        for predlist in self.conditions_list_stack[:-1]:
            # negate all of the predicates before the current one
            for predicate in predlist[:-1]:
                assert(predicate is not None)
                select = and_with_possible_none(select, ~predicate)
            # include the predicate for the current one (not negated)
            select = and_with_possible_none(select, predlist[-1])

        assert(select is not None)
        return select