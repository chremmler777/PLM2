export class ExprError extends Error {}

type Tok = { k: 'num' | 'str' | 'op' | 'id' | 'eof'; v: string | number | null };
const RE = /\s*(?:(\d+\.\d+|\d+)|('(?:[^'\\]|\\.)*')|(==|!=|<=|>=|[-+*/()<>,\[\]])|([A-Za-z_][A-Za-z0-9_]*))/y;

function tokenize(src: string): Tok[] {
  const out: Tok[] = []; let pos = 0;
  while (pos < src.length) {
    RE.lastIndex = pos; const m = RE.exec(src);
    if (!m || m[0].length === 0) { if (src.slice(pos).trim() === '') break; throw new ExprError(`bad token at ${pos}`); }
    pos = RE.lastIndex;
    if (m[1] !== undefined) out.push({ k: 'num', v: Number(m[1]) });
    else if (m[2] !== undefined) out.push({ k: 'str', v: m[2].slice(1, -1).replace(/\\'/g, "'") });
    else if (m[3] !== undefined) out.push({ k: 'op', v: m[3] });
    else out.push({ k: 'id', v: m[4] });
  }
  out.push({ k: 'eof', v: null });
  return out;
}

type Node = ['lit', unknown] | ['var', string] | ['list', Node[]] | ['neg', Node] | ['not', Node]
  | ['and', Node, Node] | ['or', Node, Node] | ['cmp', string, Node, Node] | ['bin', string, Node, Node] | ['call', string, Node[]];

class Parser {
  i = 0;
  constructor(private t: Tok[]) {}
  peek() { return this.t[this.i]; }
  is(k: Tok['k'], v?: string) { const p = this.peek(); return p.k === k && (v === undefined || p.v === v); }
  take(k?: Tok['k'], v?: string) { const p = this.peek(); if ((k && p.k !== k) || (v !== undefined && p.v !== v)) throw new ExprError(`expected ${v ?? k}, got ${p.v}`); this.i++; return p.v; }
  parse(): Node { const n = this.or(); if (!this.is('eof')) throw new ExprError(`unexpected ${this.peek().v}`); return n; }
  or(): Node { let n = this.and(); while (this.is('id', 'or')) { this.take(); n = ['or', n, this.and()]; } return n; }
  and(): Node { let n = this.not(); while (this.is('id', 'and')) { this.take(); n = ['and', n, this.not()]; } return n; }
  not(): Node { if (this.is('id', 'not')) { this.take(); return ['not', this.not()]; } return this.cmp(); }
  cmp(): Node { let n = this.add(); while (this.is('op') && ['==', '!=', '<', '<=', '>', '>='].includes(String(this.peek().v))) { const op = String(this.take()); n = ['cmp', op, n, this.add()]; } return n; }
  add(): Node { let n = this.mul(); while (this.is('op', '+') || this.is('op', '-')) { const op = String(this.take()); n = ['bin', op, n, this.mul()]; } return n; }
  mul(): Node { let n = this.unary(); while (this.is('op', '*') || this.is('op', '/')) { const op = String(this.take()); n = ['bin', op, n, this.unary()]; } return n; }
  unary(): Node { if (this.is('op', '-')) { this.take(); return ['neg', this.unary()]; } return this.primary(); }
  primary(): Node {
    const p = this.peek();
    if (p.k === 'num' || p.k === 'str') { this.take(); return ['lit', p.v]; }
    if (p.k === 'op' && p.v === '(') { this.take(); const n = this.or(); this.take('op', ')'); return n; }
    if (p.k === 'op' && p.v === '[') { this.take(); const items: Node[] = []; while (!this.is('op', ']')) { items.push(this.or()); if (this.is('op', ',')) this.take(); } this.take('op', ']'); return ['list', items]; }
    if (p.k === 'id') {
      const name = String(this.take());
      if (name === 'true' || name === 'false') return ['lit', name === 'true'];
      if (name === 'null') return ['lit', null];
      if (this.is('op', '(')) { this.take(); const args: Node[] = []; while (!this.is('op', ')')) { args.push(this.or()); if (this.is('op', ',')) this.take(); } this.take('op', ')'); return ['call', name, args]; }
      return ['var', name];
    }
    throw new ExprError(`unexpected ${p.v}`);
  }
}

const num = (x: unknown): number => (x === null || x === undefined || x === false || x === '' ? 0 : x === true ? 1 : Number(x));

function ev(n: Node, scope: Record<string, unknown>): unknown {
  switch (n[0]) {
    case 'lit': return n[1];
    case 'var': if (!(n[1] in scope)) throw new ExprError(`unknown identifier ${n[1]}`); return scope[n[1]];
    case 'list': return n[1].map((x) => ev(x, scope));
    case 'neg': return -num(ev(n[1], scope));
    case 'not': return !ev(n[1], scope);
    case 'and': return Boolean(ev(n[1], scope)) && Boolean(ev(n[2], scope));
    case 'or': return Boolean(ev(n[1], scope)) || Boolean(ev(n[2], scope));
    case 'cmp': {
      const a = ev(n[2], scope), b = ev(n[3], scope);
      if (n[1] === '==') return (a ?? null) === (b ?? null);
      if (n[1] === '!=') return (a ?? null) !== (b ?? null);
      if (typeof a === 'string' && typeof b === 'string') {
        return n[1] === '<' ? a < b : n[1] === '<=' ? a <= b : n[1] === '>' ? a > b : a >= b;
      }
      const x = num(a), y = num(b);
      return n[1] === '<' ? x < y : n[1] === '<=' ? x <= y : n[1] === '>' ? x > y : x >= y;
    }
    case 'bin': {
      const a = num(ev(n[2], scope)), b = num(ev(n[3], scope));
      return n[1] === '+' ? a + b : n[1] === '-' ? a - b : n[1] === '*' ? a * b : b === 0 ? 0 : a / b;
    }
    case 'call': {
      const [, name, args] = n;
      if (name === 'count' || name === 'sum') {
        if (args.length !== 1) throw new ExprError(`${name} takes one argument`);
        const rows = (scope._rows as Record<string, unknown>[] | undefined) ?? [];
        const vals = rows.map((r) => ev(args[0], { ...scope, ...r }));
        return name === 'count' ? vals.filter(Boolean).length : vals.reduce<number>((s, v) => s + num(v), 0);
      }
      const vals = args.map((a) => ev(a, scope));
      if (name === 'band') {
        const x = num(vals[0]); const def = vals[vals.length - 1];
        for (const band of vals.slice(1, -1) as [unknown, unknown][]) if (x <= num(band[0])) return band[1];
        return def;
      }
      if (name === 'today') {
        const d = new Date();
        const yyyy = d.getFullYear();
        const mm = String(d.getMonth() + 1).padStart(2, '0');
        const dd = String(d.getDate()).padStart(2, '0');
        return `${yyyy}-${mm}-${dd}`;
      }
      if (name === 'days_between') {
        const a = new Date(String(vals[0]).slice(0, 10)), b = new Date(String(vals[1]).slice(0, 10));
        return Math.round((b.getTime() - a.getTime()) / 86400000);
      }
      throw new ExprError(`unknown function ${name}`);
    }
  }
}

const cache = new Map<string, Node>();
export function evaluate(expr: string, scope: Record<string, unknown>): unknown {
  let ast = cache.get(expr);
  if (!ast) { ast = new Parser(tokenize(expr)).parse(); cache.set(expr, ast); }
  return ev(ast, scope);
}
