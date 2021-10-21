"""
Tools for converting from a three-address code control flow graph
to static single assignment form
"""

from collections import Counter

import networkx
from networkx.algorithms.shortest_paths.unweighted import predecessor

import tac_cfg
import ssa
from util import assert_never


def _compute_blocks_setting_vars(
    function: ssa.Function,
) -> dict[ssa.AssignLHS, set[ssa.Block]]:

    result: dict[ssa.AssignLHS, set[ssa.Block]] = dict()

    for block in function.body.nodes:
        block: ssa.Block = block
        for assignment in block.assignments:
            var = assignment.lhs

            if var not in result:
                result[var] = set()

            result[var].add(block)

    return result


def _compute_dominance_tree(function: ssa.Function) -> dict[ssa.Block, set[ssa.Block]]:
    dominance_tree_dict: dict[
        ssa.Block, ssa.Block
    ] = networkx.algorithms.immediate_dominators(
        G=function.body, start=function.entry_block
    )

    result: dict[ssa.Block, set[ssa.Block]] = dict()
    for k, v in dominance_tree_dict.items():
        if v not in result:
            result[v] = set()

        result[v].add(k)

    return result


def _tac_cfg_to_ssa_struct(tac_cfg_function: tac_cfg.Function) -> ssa.Function:
    """
    Convert a `tac_cfg.Function` to an `ssa.Function` without
    trying to enforce any SSA properties.
    The output has no Phi-functions and may assign
    to the same variable multiple times.
    """

    cfg = networkx.DiGraph()
    mapping: dict[tac_cfg.Block, ssa.Block] = dict()

    for tac_cfg_block in tac_cfg_function.body.nodes:
        tac_cfg_block: tac_cfg.Block = tac_cfg_block
        ssa_block = ssa.Block(
            phi_functions=[],
            assignments=tac_cfg_block.assignments,
            terminator=tac_cfg_block.terminator,
        )
        cfg.add_node(ssa_block)
        mapping[tac_cfg_block] = ssa_block

    for source_block, dest_block, branch_kind in tac_cfg_function.body.edges(
        data="branch_kind"
    ):
        source_block: tac_cfg.Block = source_block
        dest_block: tac_cfg.Block = dest_block
        branch_kind: tac_cfg.BranchKind = branch_kind
        branch_kind: ssa.BranchKind = branch_kind
        cfg.add_edge(
            u_of_edge=mapping[source_block],
            v_of_edge=mapping[dest_block],
            branch_kind=branch_kind,
        )

    return ssa.Function(
        parameters=tac_cfg_function.parameters,
        body=cfg,
        entry_block=mapping[tac_cfg_function.entry_block],
        exit_block=mapping[tac_cfg_function.exit_block],
    )


def _subscript_var(var: ssa.Var, i: int):
    return ssa.Var(f"{var.name}!{i}")


def tac_cfg_to_ssa(tac_cfg_function: tac_cfg.Function) -> ssa.Function:
    result = _tac_cfg_to_ssa_struct(tac_cfg_function)

    dominance_frontiers: dict[
        ssa.Block, set[ssa.Block]
    ] = networkx.algorithms.dominance_frontiers(G=result.body, start=result.entry_block)

    dominance_tree = _compute_dominance_tree(result)

    blocks_setting_vars = _compute_blocks_setting_vars(result)

    # Place Phi-functions

    iter_count = 0
    has_already: Counter[ssa.Block] = Counter()
    work: Counter[ssa.Block] = Counter()
    W: set[ssa.Block] = set()

    for V in blocks_setting_vars.keys():
        iter_count += 1

        for X in blocks_setting_vars[V]:
            work[X] = iter_count
            W.add(X)

        while W != set():
            X = W.pop()
            for Y in dominance_frontiers[X]:
                Y: ssa.Block = Y
                if has_already[Y] < iter_count:
                    num_predecessors = sum(1 for _ in result.body.predecessors(Y))
                    Y.phi_functions.append(ssa.Phi(lhs=V, rhs=[V] * num_predecessors))
                    has_already[Y] = iter_count
                    if work[Y] < iter_count:
                        work[Y] = iter_count
                        W.add(Y)

    # Rename variables

    S: dict[ssa.AssignLHS, list[int]] = dict()
    C: dict[ssa.AssignLHS, int] = dict()

    for V in result.parameters:
        C[V] = 1
        S[V] = [0]

    for V in blocks_setting_vars.keys():
        C[V] = 0
        S[V] = list()

    def search(X: ssa.Block):
        old_lhs: dict[ssa.Assign, ssa.AssignLHS] = dict()

        for A in X.assignments:
            if isinstance(A.rhs, ssa.Index):
                pass  # TODO: Support this
            elif isinstance(A.rhs, ssa.ConstantInt):
                pass
            elif isinstance(A.rhs, ssa.Var):
                V = A.rhs
                A.rhs = _subscript_var(V, S[V][-1])
            elif isinstance(A.rhs, ssa.BinOp):
                V = A.rhs.left
                A.rhs.left = _subscript_var(V, S[V][-1])
                V = A.rhs.right
                A.rhs.right = _subscript_var(V, S[V][-1])
            else:
                assert_never(A.rhs)

            V = A.lhs
            i = C[V]

            if isinstance(V, ssa.Index):
                pass  # TODO: Support this
            elif isinstance(V, ssa.Var):
                old_lhs[A] = A.lhs
                A.lhs = _subscript_var(V, i)
            else:
                assert_never(V)

            S[V].append(i)
            C[V] = i + 1

        for Y in result.body.successors(X):
            Y: ssa.Block
            j = [
                i
                for i, predecessor in enumerate(result.body.predecessors(Y))
                if predecessor == X
            ][0]
            for F in Y.phi_functions:
                V = F.rhs[j]
                i = S[V][-1]
                if isinstance(V, ssa.Index):
                    pass  # TODO: Support this
                elif isinstance(V, ssa.Var):
                    F.rhs[j] = _subscript_var(V, i)
                else:
                    assert_never(V)

        for Y in dominance_tree[X]:
            search(Y)

        for A in X.assignments:
            V = old_lhs[A]
            S[V].pop()

    search(result.entry_block)

    return result
