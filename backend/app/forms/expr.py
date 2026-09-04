"""Tiny expression language for computed form fields.

Mirrors frontend/src/forms/expr.ts; both are checked against
app/data/forms/expr_vectors.json.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any

class ExprError(Exception):
    pass

_TOKEN = re.compile(r"\s*(?:(\d+\.\d+|\d+)|('(?:[^'\\]|\\.)*')|(==|!=|<=|>=|[-+*/()<>,\[\]])|([A-Za-z_][A-Za-z0-9_]*))")

def _tokenize(src: str) -> list[tuple[str, Any]]:
    out, pos = [], 0
    while pos < len(src):
        m = _TOKEN.match(src, pos)
        if not m or m.end() == pos:
            if src[pos:].strip() == "":
                break
            raise ExprError(f"bad token at {pos}: {src[pos:pos+10]!r}")
        pos = m.end()
        num, s, op, ident = m.groups()
        if num is not None:
            out.append(("num", float(num) if "." in num else int(num)))
        elif s is not None:
            out.append(("str", s[1:-1].replace("\\'", "'")))
        elif op is not None:
            out.append(("op", op))
        else:
            out.append(("id", ident))
    out.append(("eof", None))
    return out

class _Parser:
    def __init__(self, tokens):
        self.t, self.i = tokens, 0
    def peek(self):
        return self.t[self.i]
    def take(self, kind=None, val=None):
        k, v = self.t[self.i]
        if (kind and k != kind) or (val is not None and v != val):
            raise ExprError(f"expected {val or kind}, got {v!r}")
        self.i += 1
        return v
    # precedence climbing
    def parse(self):
        node = self.p_or()
        if self.peek()[0] != "eof":
            raise ExprError(f"unexpected {self.peek()[1]!r}")
        return node
    def p_or(self):
        n = self.p_and()
        while self.peek() == ("id", "or"):
            self.take(); n = ("or", n, self.p_and())
        return n
    def p_and(self):
        n = self.p_not()
        while self.peek() == ("id", "and"):
            self.take(); n = ("and", n, self.p_not())
        return n
    def p_not(self):
        if self.peek() == ("id", "not"):
            self.take(); return ("not", self.p_not())
        return self.p_cmp()
    def p_cmp(self):
        n = self.p_add()
        while self.peek()[0] == "op" and self.peek()[1] in ("==", "!=", "<", "<=", ">", ">="):
            op = self.take(); n = ("cmp", op, n, self.p_add())
        return n
    def p_add(self):
        n = self.p_mul()
        while self.peek()[0] == "op" and self.peek()[1] in ("+", "-"):
            op = self.take(); n = ("bin", op, n, self.p_mul())
        return n
    def p_mul(self):
        n = self.p_unary()
        while self.peek()[0] == "op" and self.peek()[1] in ("*", "/"):
            op = self.take(); n = ("bin", op, n, self.p_unary())
        return n
    def p_unary(self):
        if self.peek() == ("op", "-"):
            self.take(); return ("neg", self.p_unary())
        return self.p_primary()
    def p_primary(self):
        k, v = self.peek()
        if k == "num": self.take(); return ("lit", v)
        if k == "str": self.take(); return ("lit", v)
        if k == "op" and v == "(":
            self.take(); n = self.p_or(); self.take("op", ")"); return n
        if k == "op" and v == "[":
            self.take(); items = []
            while self.peek() != ("op", "]"):
                items.append(self.p_or())
                if self.peek() == ("op", ","): self.take()
            self.take("op", "]"); return ("list", items)
        if k == "id":
            self.take()
            if v in ("true", "false"): return ("lit", v == "true")
            if v == "null": return ("lit", None)
            if self.peek() == ("op", "("):
                self.take(); args = []
                while self.peek() != ("op", ")"):
                    args.append(self.p_or())
                    if self.peek() == ("op", ","): self.take()
                self.take("op", ")"); return ("call", v, args)
            return ("var", v)
        raise ExprError(f"unexpected {v!r}")

def _num(x):
    return 0 if x is None or x is False else (1 if x is True else x)

def _eval(node, scope):
    kind = node[0]
    if kind == "lit": return node[1]
    if kind == "var":
        if node[1] not in scope: raise ExprError(f"unknown identifier {node[1]}")
        return scope[node[1]]
    if kind == "list": return [_eval(n, scope) for n in node[1]]
    if kind == "neg": return -_num(_eval(node[1], scope))
    if kind == "not": return not _eval(node[1], scope)
    if kind == "and": return bool(_eval(node[1], scope)) and bool(_eval(node[2], scope))
    if kind == "or": return bool(_eval(node[1], scope)) or bool(_eval(node[2], scope))
    if kind == "cmp":
        op, a, b = node[1], _eval(node[2], scope), _eval(node[3], scope)
        if op == "==": return a == b
        if op == "!=": return a != b
        a, b = _num(a), _num(b)
        return {"<": a < b, "<=": a <= b, ">": a > b, ">=": a >= b}[op]
    if kind == "bin":
        op, a, b = node[1], _num(_eval(node[2], scope)), _num(_eval(node[3], scope))
        if op == "+": return a + b
        if op == "-": return a - b
        if op == "*": return a * b
        return 0 if b == 0 else a / b
    if kind == "call":
        name, args = node[1], node[2]
        if name in ("count", "sum"):
            if len(args) != 1: raise ExprError(f"{name} takes one argument")
            rows = scope.get("_rows") or []
            vals = [_eval(args[0], {**scope, **row}) for row in rows]
            return sum(1 for v in vals if v) if name == "count" else sum(_num(v) for v in vals)
        vals = [_eval(a, scope) for a in args]
        if name == "band":
            x, *bands, default = vals
            x = _num(x)
            for limit, label in bands:
                if x <= _num(limit): return label
            return default
        if name == "today": return date.today().isoformat()
        if name == "days_between":
            a, b = date.fromisoformat(str(vals[0])[:10]), date.fromisoformat(str(vals[1])[:10])
            return (b - a).days
        raise ExprError(f"unknown function {name}")
    raise ExprError(f"bad node {kind}")

_CACHE: dict[str, tuple] = {}

def evaluate(expr: str, scope: dict) -> Any:
    ast = _CACHE.get(expr)
    if ast is None:
        ast = _Parser(_tokenize(expr)).parse()
        _CACHE[expr] = ast
    return _eval(ast, scope)
