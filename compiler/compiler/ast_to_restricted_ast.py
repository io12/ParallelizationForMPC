"""
Tools for checking if a Python AST fits a restricted subset,
and for converting to a data type that reflects that restricted subset.
"""

import ast
from dataclasses import dataclass
from typing import Optional, final, NoReturn, Union, cast

from . import restricted_ast
from .ast_shared import VarType, VarVisibility, DataType


@dataclass
class _SourceCodeInfo:
    filename: str
    text: str


@dataclass
class _StrictNodeVisitor(ast.NodeVisitor):
    source_code_info: _SourceCodeInfo

    def error_message(self) -> str:
        return "Unknown error"

    @final
    def raise_syntax_error(
        self, node: ast.AST, message: Optional[str] = None
    ) -> NoReturn:
        if message is None:
            message = self.error_message()

        raise SyntaxError(
            message,
            (
                self.source_code_info.filename,
                node.lineno,
                node.col_offset + 1,
                self.source_code_info.text.splitlines()[node.lineno - 1],
            ),
        )

    @final
    def generic_visit(self, node: ast.AST):
        self.raise_syntax_error(node)


class _NameGetter(_StrictNodeVisitor):
    def error_message(self) -> str:
        return "Expected a name"

    def visit_Name(self, node: ast.Name) -> restricted_ast.Var:
        return restricted_ast.Var(node.id)


@dataclass
class _NameExpector(_StrictNodeVisitor):
    name: str

    def error_message(self) -> str:
        return f"Expected `{self.name}`"

    def visit_Name(self, node: ast.Name):
        if node.id != self.name:
            self.raise_syntax_error(node)


class _DocstringExpector(_StrictNodeVisitor):
    def error_message(self) -> str:
        return "Expected docstring"

    def visit_Constant(self, node: ast.Constant) -> None:
        if type(node.value) != str:
            self.raise_syntax_error(node)


class _LoopBoundConverter(_StrictNodeVisitor):
    def error_message(self) -> str:
        return "Invalid loop bound: Expected an integer or variable"

    def visit_Constant(self, node: ast.Constant) -> restricted_ast.LoopBound:
        if not isinstance(node.value, int):
            self.raise_syntax_error(node)
        return restricted_ast.Constant(node.value, DataType.INT)

    def visit_Name(self, node: ast.Name) -> restricted_ast.LoopBound:
        return restricted_ast.Var(name=node.id)


class _RangeBoundsGetter(_StrictNodeVisitor):
    def error_message(self) -> str:
        return "Expected a call to `range()`"

    def visit_Call(
        self, node: ast.Call
    ) -> tuple[restricted_ast.LoopBound, restricted_ast.LoopBound]:
        _NameExpector(self.source_code_info, "range").visit(node.func)
        if node.keywords != []:
            self.raise_syntax_error(
                node, "Keyword arguments in call to `range()` unsupported"
            )
        bounds = [
            _LoopBoundConverter(self.source_code_info).visit(arg) for arg in node.args
        ]
        if len(bounds) == 1:
            return (restricted_ast.Constant(0, DataType.INT), bounds[0])
        elif len(bounds) == 2:
            return (bounds[0], bounds[1])
        else:
            self.raise_syntax_error(
                node, "Number of `range()` arguments must be 1 or 2"
            )


class _SubscriptIndexConverter(_StrictNodeVisitor):
    def error_message(self) -> str:
        return "Expected a list subscript index"

    def visit_Name(self, node: ast.Name) -> restricted_ast.SubscriptIndex:
        return restricted_ast.Var(name=node.id)

    def visit_Constant(self, node: ast.Constant) -> restricted_ast.SubscriptIndex:
        if type(node.value) == int:
            return restricted_ast.Constant(value=node.value, datatype=DataType.INT)
        elif type(node.value) == bool:
            return restricted_ast.Constant(value=node.value, datatype=DataType.BOOL)
        else:
            self.raise_syntax_error(node, "Unsupported constant type")

    def visit_BinOp(self, node: ast.BinOp) -> restricted_ast.SubscriptIndex:
        operator = _convert_binary_operator(node.op)
        if operator is None:
            self.raise_syntax_error(node, "Unsupported binary operator")
        return restricted_ast.SubscriptIndexBinOp(
            left=_SubscriptIndexConverter(self.source_code_info).visit(node.left),
            operator=operator,
            right=_SubscriptIndexConverter(self.source_code_info).visit(node.right),
        )

    def visit_UnaryOp(self, node: ast.UnaryOp) -> restricted_ast.SubscriptIndex:
        operator = _convert_unary_operator(node.op)
        if operator is None:
            self.raise_syntax_error(node, "Unsupported unary operator")
        return restricted_ast.SubscriptIndexUnaryOp(
            operator=operator,
            operand=_SubscriptIndexConverter(self.source_code_info).visit(node.operand),
        )


def _convert_subscript(
    source_code_info: _SourceCodeInfo, node: ast.Subscript
) -> restricted_ast.Subscript:
    return restricted_ast.Subscript(
        array=_NameGetter(source_code_info).visit(node.value),
        index=_SubscriptIndexConverter(source_code_info).visit(node.slice),
    )


class _AssignLHSConverter(_StrictNodeVisitor):
    def error_message(self) -> str:
        return "Expected a subscript or variable"

    def visit_Subscript(self, node: ast.Subscript) -> restricted_ast.AssignLHS:
        return _convert_subscript(self.source_code_info, node)

    def visit_Name(self, node: ast.Name) -> restricted_ast.AssignLHS:
        return restricted_ast.Var(name=node.id)


def _convert_binary_operator(op: ast.operator) -> Optional[restricted_ast.BinOpKind]:
    TABLE: dict[type[ast.operator], restricted_ast.BinOpKind] = {
        ast.Add: restricted_ast.BinOpKind.ADD,
        ast.Sub: restricted_ast.BinOpKind.SUB,
        ast.Mult: restricted_ast.BinOpKind.MUL,
        ast.FloorDiv: restricted_ast.BinOpKind.DIV,
        ast.Mod: restricted_ast.BinOpKind.MOD,
        ast.LShift: restricted_ast.BinOpKind.SHL,
        ast.RShift: restricted_ast.BinOpKind.SHR,
    }
    try:
        return TABLE[type(op)]
    except KeyError:
        return None


def _convert_comparison_operator(op: ast.cmpop) -> Optional[restricted_ast.BinOpKind]:
    TABLE: dict[type[ast.cmpop], restricted_ast.BinOpKind] = {
        ast.Eq: restricted_ast.BinOpKind.EQ,
        ast.NotEq: restricted_ast.BinOpKind.NOT_EQ,
        ast.Lt: restricted_ast.BinOpKind.LT,
        ast.LtE: restricted_ast.BinOpKind.LT_E,
        ast.Gt: restricted_ast.BinOpKind.GT,
        ast.GtE: restricted_ast.BinOpKind.GT_E,
    }
    try:
        return TABLE[type(op)]
    except KeyError:
        return None


def _convert_boolean_operator(op: ast.boolop) -> Optional[restricted_ast.BinOpKind]:
    TABLE: dict[type[ast.boolop], restricted_ast.BinOpKind] = {
        ast.And: restricted_ast.BinOpKind.AND,
        ast.Or: restricted_ast.BinOpKind.OR,
    }
    try:
        return TABLE[type(op)]
    except KeyError:
        return None


def _convert_unary_operator(op: ast.unaryop) -> Optional[restricted_ast.UnaryOpKind]:
    TABLE: dict[type[ast.unaryop], restricted_ast.UnaryOpKind] = {
        ast.USub: restricted_ast.UnaryOpKind.NEGATE,
        ast.Not: restricted_ast.UnaryOpKind.NOT,
    }
    try:
        return TABLE[type(op)]
    except KeyError:
        return None


class _ExpressionConverter(_StrictNodeVisitor):
    def error_message(self) -> str:
        return "Expected an expression"

    def visit_Name(self, node: ast.Name) -> restricted_ast.Expression:
        return restricted_ast.Var(name=node.id)

    def visit_Constant(self, node: ast.Constant) -> restricted_ast.Expression:
        if type(node.value) == int:
            return restricted_ast.Constant(value=node.value, datatype=DataType.INT)
        elif type(node.value) == bool:
            return restricted_ast.Constant(value=node.value, datatype=DataType.BOOL)
        else:
            self.raise_syntax_error(node, "Unsupported constant type")

    def visit_Subscript(self, node: ast.Subscript) -> restricted_ast.Expression:
        return _convert_subscript(self.source_code_info, node)

    def visit_List(self, node: ast.List) -> restricted_ast.Expression:
        return restricted_ast.List(
            items=[
                _ExpressionConverter(self.source_code_info).visit(elt)
                for elt in node.elts
            ]
        )

    def visit_Tuple(self, node: ast.Tuple) -> restricted_ast.Expression:
        return restricted_ast.Tuple(
            items=[
                _ExpressionConverter(self.source_code_info).visit(elt)
                for elt in node.elts
            ]
        )

    def visit_BinOp(self, node: ast.BinOp) -> restricted_ast.Expression:
        operator = _convert_binary_operator(node.op)
        if operator is None:
            self.raise_syntax_error(node, "Unsupported binary operator")
        return restricted_ast.BinOp(
            left=_ExpressionConverter(self.source_code_info).visit(node.left),
            operator=operator,
            right=_ExpressionConverter(self.source_code_info).visit(node.right),
        )

    def visit_Compare(self, node: ast.Compare) -> restricted_ast.Expression:
        if len(node.ops) != 1:
            self.raise_syntax_error(
                node, "Comparisons with multiple operators are unsupported"
            )
        if len(node.comparators) != 1:
            self.raise_syntax_error(
                node, "Comparisons with multiple comparators are unsupported"
            )
        operator = _convert_comparison_operator(node.ops[0])
        if operator is None:
            self.raise_syntax_error(node, "Unsupported comparison operator")
        return restricted_ast.BinOp(
            left=_ExpressionConverter(self.source_code_info).visit(node.left),
            operator=operator,
            right=_ExpressionConverter(self.source_code_info).visit(
                node.comparators[0]
            ),
        )

    def visit_BoolOp(self, node: ast.BoolOp) -> restricted_ast.Expression:
        operator = _convert_boolean_operator(node.op)
        if operator is None:
            self.raise_syntax_error(node, "Unsupported boolean operator")
        result = restricted_ast.BinOp(
            left=_ExpressionConverter(self.source_code_info).visit(node.values[0]),
            operator=operator,
            right=_ExpressionConverter(self.source_code_info).visit(node.values[1]),
        )
        for operand in node.values[2:]:
            result = restricted_ast.BinOp(
                left=result,
                operator=operator,
                right=_ExpressionConverter(self.source_code_info).visit(operand),
            )
        return result

    def visit_UnaryOp(self, node: ast.UnaryOp) -> restricted_ast.Expression:
        operator = _convert_unary_operator(node.op)
        if operator is None:
            self.raise_syntax_error(node, "Unsupported unary operator")
        return restricted_ast.UnaryOp(
            operator=operator,
            operand=_ExpressionConverter(self.source_code_info).visit(node.operand),
        )


def _convert_statements(
    source_code_info: _SourceCodeInfo, statements: list[ast.stmt]
) -> list[restricted_ast.Statement]:
    converted_statements: list[Optional[restricted_ast.Statement]] = [
        _StatementConverter(source_code_info).visit(statement)
        for statement in statements
    ]
    return [statement for statement in converted_statements if statement is not None]


class _StatementConverter(_StrictNodeVisitor):
    def error_message(self) -> str:
        return "Expected a statement"

    def visit_For(self, node: ast.For) -> Optional[restricted_ast.Statement]:
        if node.orelse != []:
            self.raise_syntax_error(node, "Unsupported `else` in `for` loop")
        (bound_low, bound_high) = _RangeBoundsGetter(self.source_code_info).visit(
            node.iter
        )
        counter = _NameGetter(self.source_code_info).visit(node.target)
        return restricted_ast.For(
            counter=restricted_ast.Var(name=counter.name),
            bound_low=bound_low,
            bound_high=bound_high,
            body=_convert_statements(self.source_code_info, node.body),
        )

    def visit_If(self, node: ast.If) -> Optional[restricted_ast.Statement]:
        return restricted_ast.If(
            condition=_ExpressionConverter(self.source_code_info).visit(node.test),
            then_body=_convert_statements(self.source_code_info, node.body),
            else_body=_convert_statements(self.source_code_info, node.orelse),
        )

    def visit_Assign(self, node: ast.Assign) -> Optional[restricted_ast.Statement]:
        if len(node.targets) != 1:
            self.raise_syntax_error(node, "Assignments must have one target")
        return restricted_ast.Assign(
            lhs=_AssignLHSConverter(self.source_code_info).visit(node.targets[0]),
            rhs=_ExpressionConverter(self.source_code_info).visit(node.value),
        )

    def visit_AnnAssign(
        self, node: ast.AnnAssign
    ) -> Optional[restricted_ast.Statement]:
        if node.value is None:
            self.raise_syntax_error(node, "Annotated assignment without a value")
        return restricted_ast.Assign(
            lhs=_AssignLHSConverter(self.source_code_info).visit(node.target),
            rhs=_ExpressionConverter(self.source_code_info).visit(node.value),
        )

    def visit_AugAssign(
        self, node: ast.AugAssign
    ) -> Optional[restricted_ast.Statement]:
        operator = _convert_binary_operator(node.op)
        if operator is None:
            self.raise_syntax_error(node, "Unsupported binary operator")
        target: restricted_ast.AssignLHS = _AssignLHSConverter(
            self.source_code_info
        ).visit(node.target)
        return restricted_ast.Assign(
            lhs=target,
            rhs=restricted_ast.BinOp(
                left=target,
                operator=operator,
                right=_ExpressionConverter(self.source_code_info).visit(node.value),
            ),
        )

    def visit_Expr(self, node: ast.Expr) -> Optional[restricted_ast.Statement]:
        # Ignore docstrings
        _DocstringExpector(self.source_code_info).visit(node.value)
        return None


class _ReturnValueGetter(_StrictNodeVisitor):
    def error_message(self) -> str:
        return "Expected `return`"

    def visit_Return(self, node: ast.Return) -> restricted_ast.Expression:
        if node.value is None:
            self.raise_syntax_error(node, "Expected `return` value")
        return _ExpressionConverter(self.source_code_info).visit(node.value)


class _TypeConverter(_StrictNodeVisitor):
    def error_message(self) -> str:
        return "Expected a type"

    def visit_Name(self, node: ast.Name) -> VarType:
        if node.id != "int":
            self.raise_syntax_error(node, "Only `int` is supported")

        return VarType(VarVisibility.SHARED, 0, DataType.INT)

    def visit_Subscript(self, node: ast.Subscript) -> VarType:
        if not isinstance(node.value, ast.Name):
            self.raise_syntax_error(node, "Generic types must be named")

        if node.value.id != "list":
            self.raise_syntax_error(
                node, "Only `list` is supported as a collection of types"
            )

        if not isinstance(node.slice, ast.Name):
            self.raise_syntax_error(
                node, "Generic types must be indexed by a single type"
            )

        if node.slice.id != "int":
            self.raise_syntax_error(
                node, "Only one-dimensional `list`s are currently supported"
            )

        subtype = _TypeConverter(self.source_code_info).visit(node.slice)

        return VarType(VarVisibility.SHARED, subtype.dims + 1, subtype.datatype)


class _FunctionConverter(_StrictNodeVisitor):
    def visit_FunctionDef(self, node: ast.FunctionDef) -> restricted_ast.Function:
        # TODO: Check parameter and return types
        if node.decorator_list != []:
            self.raise_syntax_error(node, "Decorators unsupported")
        if len(node.body) == 0:
            self.raise_syntax_error(node, "Function has empty body")
        parameters = [
            restricted_ast.Parameter(
                var=restricted_ast.Var(arg.arg),
                var_type=VarType(VarVisibility.PLAINTEXT, 0, DataType.INT)
                if arg.annotation is None
                else _TypeConverter(self.source_code_info).visit(arg.annotation),
            )
            for arg in node.args.args
        ]

        party_idx = 0
        for parameter in parameters:
            if parameter.var_type.visibility == VarVisibility.SHARED:
                parameter.party_idx = party_idx
                party_idx += 1

        return restricted_ast.Function(
            # TODO: Exclude other kinds of arguments
            name=node.name,
            parameters=parameters,
            body=_convert_statements(self.source_code_info, node.body[:-1]),
            return_value=_ReturnValueGetter(self.source_code_info).visit(node.body[-1]),
        )


class _ModuleConverter(_StrictNodeVisitor):
    def error_message(self) -> str:
        return "Expected module"

    def visit_Module(self, node: ast.Module) -> restricted_ast.Function:
        # TODO: Support larger modules
        main_function = _FunctionConverter(self.source_code_info).visit(
            [
                statement
                for statement in node.body
                if isinstance(statement, ast.FunctionDef)
            ][0]
        )

        def get_root_call(func: ast.Call) -> Optional[ast.Call]:
            assert isinstance(func.func, ast.Name)
            if func.func.id == main_function.name:
                return func
            if len(func.args) != 1 or not isinstance(func.args[0], ast.Call):
                return None
            return get_root_call(func.args[0])

        def expr_to_constant(expr: ast.expr) -> Union[int, list[int]]:
            if isinstance(expr, ast.Num) and isinstance(expr.n, int):
                return expr.n
            elif isinstance(expr, (ast.List, ast.Tuple)) and all(
                isinstance(e, ast.Constant) and isinstance(e.value, int)
                for e in expr.elts
            ):
                return [cast(ast.Constant, e).value for e in expr.elts]
            else:
                self.raise_syntax_error(
                    expr, "Expected a constant integer or list of integers"
                )

        var_values = dict()
        for statement in node.body:
            if isinstance(statement, ast.Assign):
                target = statement.targets[0]
                if not isinstance(target, ast.Name):
                    self.raise_syntax_error(target, "Expected a variable")
                var_values[target.id] = expr_to_constant(statement.value)
            elif isinstance(statement, ast.Expr) and isinstance(
                statement.value, ast.Call
            ):
                call = get_root_call(statement.value)
                if call is None:
                    continue

                if len(call.args) != len(main_function.parameters):
                    self.raise_syntax_error(
                        call,
                        f"Incorrect number of arguments to {main_function.name} (expected {len(main_function.parameters)}, got {len(call.args)})",
                    )

                for i, arg in enumerate(call.args):
                    if isinstance(arg, ast.Name):
                        if arg.id not in var_values:
                            self.raise_syntax_error(
                                arg,
                                f"Unknown variable {arg.id} passed to {main_function.name}",
                            )
                        value = var_values[arg.id]
                    else:
                        value = expr_to_constant(arg)

                    main_function.parameters[i].default_values.append(value)

        return main_function


def ast_to_restricted_ast(
    node: ast.AST, filename: str, text: str
) -> restricted_ast.Function:
    info = _SourceCodeInfo(filename=filename, text=text)
    return _ModuleConverter(info).visit(node)
