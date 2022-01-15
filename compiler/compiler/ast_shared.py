from enum import Enum
from typing import Generic, TypeVar, Union, Optional, Protocol
from dataclasses import dataclass, field
from textwrap import indent

import networkx  # type: ignore


class VarVisibility(Enum):
    PLAINTEXT = "plaintext"
    SHARED = "shared"

    def __str__(self) -> str:
        return self.value

    __repr__ = __str__


class DataType(Enum):
    INT = "int"
    BOOL = "bool"

    # TODO: allow tuples to hold multiple types

    def to_cpp(self) -> str:
        if self == DataType.INT:
            return "std::uint32_t"
        elif self == DataType.BOOL:
            return "bool"
        else:
            raise Exception("Unknown data type")

    def __str__(self) -> str:
        return self.value

    __repr__ = __str__


@dataclass
class VarType:
    visibility: Optional[VarVisibility] = None
    dims: Optional[int] = None
    datatype: Optional[DataType] = None

    def drop_dim(self) -> "VarType":
        if self.dims is None:
            return VarType(self.visibility, None, self.datatype)
        else:
            return VarType(self.visibility, self.dims - 1, self.datatype)

    def add_dim(self) -> "VarType":
        if self.dims is None:
            return VarType(self.visibility, None, self.datatype)
        else:
            return VarType(self.visibility, self.dims + 1, self.datatype)

    def is_plaintext(self) -> bool:
        return self.visibility == VarVisibility.PLAINTEXT

    def is_shared(self) -> bool:
        return self.visibility == VarVisibility.SHARED

    def could_become(self, supertype: "VarType") -> bool:
        return (
            self.visibility in [supertype.visibility, None]
            and self.datatype in [supertype.datatype, None]
            and self.dims in [supertype.dims, None]
        )

    def is_complete(self) -> bool:
        return (
            self.visibility is not None
            and self.datatype is not None
            and self.dims is not None
        )

    @staticmethod
    def merge(
        *types: "VarType",
        mixed_shared_plaintext_allowed=True,
        mixed_datatypes_allowed=False,
    ) -> "VarType":
        assert len(types) > 0

        # TODO: switch all type errors to syntax errors with the locations of the offending
        # code in the original source code

        merged_type = VarType()

        elem_visibilities = [t.visibility for t in types]
        elem_dims = [t.dims for t in types if t.dims is not None]
        elem_datatypes = [t.datatype for t in types if t.datatype is not None]

        # Determine the visibility of the merged type
        if (
            len(set(filter(lambda x: x is not None, elem_visibilities))) > 1
            and not mixed_shared_plaintext_allowed
        ):
            raise TypeError(
                "Cannot merge types with different visibilities:\n{}".format(
                    "\n".join(repr(t) for t in types)
                )
            )
        if any(v == VarVisibility.SHARED for v in elem_visibilities):
            merged_type.visibility = VarVisibility.SHARED
        elif all(v == VarVisibility.PLAINTEXT for v in elem_visibilities):
            merged_type.visibility = VarVisibility.PLAINTEXT

        # Determine the dimensionality of the merged type
        if len(set(elem_dims)) > 1:
            raise TypeError(
                "Cannot merge types with different dimensionality:\n{}".format(
                    "\n".join(repr(t) for t in types)
                )
            )
        if len(elem_dims) > 0:
            merged_type.dims = elem_dims[0]

        # Determine the datatype of the merged type
        if len(set(elem_datatypes)) > 1 and not mixed_datatypes_allowed:
            raise TypeError(
                "Cannot merge types with different datatypes:\n{}".format(
                    "\n".join(repr(t) for t in types)
                )
            )
        if len(elem_datatypes) > 0:
            merged_type.datatype = elem_datatypes[0]

        return merged_type

    def to_cpp(self) -> str:
        assert self.visibility is not None
        assert self.datatype is not None
        assert self.dims is not None

        str_rep = ""
        for _ in range(self.dims):
            str_rep += "std::vector<"
        if self.visibility == VarVisibility.PLAINTEXT:
            str_rep += self.datatype.to_cpp()
        elif self.visibility == VarVisibility.SHARED:
            if self.datatype == DataType.INT:
                str_rep += "encrypto::motion::SecureUnsignedInteger"
            elif self.datatype == DataType.BOOL:
                # TODO: check that this is the correct type
                str_rep += "encrypto::motion::ShareWrapper"
        for _ in range(self.dims):
            str_rep += ">"
        return str_rep

    def __str__(self) -> str:
        str_rep = f"{self.visibility}["
        if self.dims is not None:
            for _ in range(self.dims):
                str_rep += "list["
        str_rep += f"{self.datatype}"
        if self.dims is not None:
            for _ in range(self.dims):
                str_rep += "]"
        str_rep += "]"
        if self.dims is None:
            str_rep += "(unknown dims)"
        return str_rep


PLAINTEXT_INT = VarType(VarVisibility.PLAINTEXT, 0, DataType.INT)


@dataclass(frozen=True)
class Var:
    """A variable named `name`"""

    # This is a string for user-provided variables,
    # and an integer for temporary variables the compiler automatically generates
    name: Union[str, int]

    rename_subscript: Optional[int] = None

    def to_cpp(self) -> str:
        self_str = str(self)
        return self_str.replace("!", "_")

    def __str__(self) -> str:
        name = self.name if isinstance(self.name, str) else f"!{self.name}"
        subscript = "" if self.rename_subscript is None else f"!{self.rename_subscript}"
        return name + subscript


@dataclass
class Parameter:
    """A function parameter of the form `var: var_type`"""

    var: Var
    var_type: VarType
    default_values: list[str] = field(
        default_factory=list
    )  # generated from example function calls in the input file
    party_idx: Optional[
        int
    ] = None  # stores the party index associated with this parameter, if it is shared

    def to_cpp(self):
        return self.var_type.to_cpp() + " " + self.var.to_cpp()

    def __str__(self) -> str:
        return f"{self.var}: {self.var_type}"


@dataclass(frozen=True)
class Constant:
    """A constant with value `value`"""

    value: int
    datatype: DataType

    def to_cpp(self) -> str:
        return str(self.value)

    def __str__(self) -> str:
        return str(self.value)


LoopBound = Union[Var, Constant]


class BinOpKind(Enum):
    ADD = "+"
    SUB = "-"
    MUL = "*"
    DIV = "//"
    MOD = "%"
    SHL = "<<"
    SHR = ">>"
    LT = "<"
    GT = ">"
    LT_E = "<="
    GT_E = ">="
    EQ = "=="
    NOT_EQ = "!="
    AND = "and"
    OR = "or"

    def get_ret_datatype(self) -> DataType:
        if self in (
            BinOpKind.ADD,
            BinOpKind.SUB,
            BinOpKind.MUL,
            BinOpKind.DIV,
            BinOpKind.MOD,
            BinOpKind.SHL,
            BinOpKind.SHR,
        ):
            return DataType.INT

        elif self in (
            BinOpKind.LT,
            BinOpKind.GT,
            BinOpKind.LT_E,
            BinOpKind.GT_E,
            BinOpKind.EQ,
            BinOpKind.NOT_EQ,
            BinOpKind.AND,
            BinOpKind.OR,
        ):
            return DataType.BOOL

        else:
            raise ValueError(f"Unhandled binary operation {self}")

    def get_operand_datatypes(self) -> list[DataType]:
        if self in (
            BinOpKind.ADD,
            BinOpKind.SUB,
            BinOpKind.MUL,
            BinOpKind.DIV,
            BinOpKind.MOD,
            BinOpKind.SHL,
            BinOpKind.SHR,
            BinOpKind.LT,
            BinOpKind.GT,
            BinOpKind.LT_E,
            BinOpKind.GT_E,
        ):
            return [DataType.INT]

        elif self in (
            BinOpKind.EQ,
            BinOpKind.NOT_EQ,
            BinOpKind.AND,
            BinOpKind.OR,
        ):
            return [DataType.INT, DataType.BOOL]

        else:
            raise ValueError(f"Unhandled binary operation {self}")

    def __str__(self) -> str:
        return self.value


class UnaryOpKind(Enum):
    NEGATE = "-"
    NOT = "not"

    def get_ret_datatype(self) -> DataType:
        if self == UnaryOpKind.NEGATE:
            return DataType.INT

        elif self == UnaryOpKind.NOT:
            return DataType.BOOL

        else:
            raise ValueError(f"Unhandled unary operation {self}")

    def get_operand_datatypes(self) -> list[DataType]:
        if self == UnaryOpKind.NEGATE:
            return [DataType.INT]

        elif self == UnaryOpKind.NOT:
            return [DataType.BOOL, DataType.INT]

        else:
            raise ValueError(f"Unhandled unary operation {self}")

    def __str__(self) -> str:
        return self.value


class CppConvertible(Protocol):
    def to_cpp(self) -> str:
        ...


OPERAND = TypeVar("OPERAND", bound=CppConvertible)


@dataclass
class BinOp(Generic[OPERAND]):
    """A binary operator expression of the form `left operator right`"""

    left: OPERAND
    operator: BinOpKind
    right: OPERAND

    def to_cpp(self) -> str:
        return f"({self.left.to_cpp()} {self.operator.value} {self.right.to_cpp()})"

    def __str__(self) -> str:
        return f"({self.left} {self.operator} {self.right})"


@dataclass
class UnaryOp(Generic[OPERAND]):
    """A unary operator expression of the form `operator operand`"""

    operator: UnaryOpKind
    operand: OPERAND

    def to_cpp(self) -> str:
        return f"({self.operator.value} {self.operand.to_cpp()})"

    def __str__(self) -> str:
        return f"{self.operator} {self.operand}"


class SubscriptIndexBinOp(BinOp["SubscriptIndex"]):
    pass


class SubscriptIndexUnaryOp(UnaryOp["SubscriptIndex"]):
    pass


SubscriptIndex = Union[Var, Constant, SubscriptIndexBinOp, SubscriptIndexUnaryOp]


@dataclass(frozen=True)
class Subscript:
    """An array subscript expression of the form `array[index]`"""

    array: Var
    index: SubscriptIndex

    def to_cpp(self) -> str:
        return f"{self.array.to_cpp()}[{self.index.to_cpp()}]"

    def __hash__(self) -> int:
        return id(self)

    def __str__(self) -> str:
        return f"{self.array}[{self.index}]"


BLOCK = TypeVar("BLOCK")


@dataclass
class CFGFunction(Generic[BLOCK]):
    name: str
    parameters: list[Parameter]
    body: networkx.DiGraph
    entry_block: BLOCK
    exit_block: BLOCK

    def __str__(self) -> str:
        parameters = ", ".join([str(parameter) for parameter in self.parameters])
        block_indices = {block: i for i, block in enumerate(self.body.nodes)}
        blocks = "\n".join(
            [
                f"Block {i}:\n{indent(str(block), '    ')}"
                for i, block in enumerate(self.body.nodes)
            ]
        )
        edges = " ".join(
            [
                f"({block_indices[u]}, {block_indices[v]}, {label})"
                for u, v, label in self.body.edges(data="label")
            ]
        )
        return (
            f"Function {self.name}({parameters}):\n"
            + f"Entry block: {block_indices[self.entry_block]}\n"
            + f"Exit block: {block_indices[self.exit_block]}\n"
            + blocks
            + "\n"
            + f"Edges: {edges}"
        )
