import expression
import scheme
from utility import emit, Printable

"""
Generate variables names
"""
i = 0
def reset():
  global i
  i = 0

def gensym():
  global i
  i += 1
  return "V%s" % i

class RecursionError(ValueError):
  pass

class SchemaError(Exception):
  pass

class Operator(Printable):
  """Operator base classs"""
  def __init__(self):
    self.bound = None
    # Extra code to emit to cleanup
    self.cleanup = ""
    self.alias = self
    self._trace = []

  def children(self):
    raise NotImplementedError("Operator.children")

  def postorder(self, f):
    """Postorder traversal, applying a function to each operator.  The function
    returns an iterator"""
    for c in self.children():
      for x in c.postorder(f):
        yield x
    for x in f(self):
      yield x

  def preorder(self, f):
    """Preorder traversal, applying a function to each operator.  The function
    returns an iterator"""
    for x in f(self):
      yield x
    for c in self.children():
      for x in c.postorder(f):
        yield x

  def collectParents(self, parent_map=None):
    """Construct a dict mapping children to parents. Used in optimization"""
    if parent_map is None:
      parent_map = {}
    for c in self.children():
      parent_map.setdefault(c, []).append(self)
      c.collectParents(parentmap)

  def __eq__(self, other):
    return self.__class__ == other.__class__

  def __str__(self):
    child_str = ', '.join([str(c) for c in self.children()])
    if len(child_str) > 0:
        return "%s[%s]" % (self.shortStr(), child_str)
    return self.shortStr()

  def copy(self, other):
    self._trace = [pair for pair in other.gettrace()]
    self.bound = None

  def trace(self, key, val):
    self._trace.append((key, val))

  def gettrace(self):
    """Return a list of trace messages"""
    return self._trace

  def compiletrace(self):
    """Return the trace as a list of strings"""
    return "".join([self.language.comment("%s=%s" % (k,v)) for k,v in self.gettrace()])

  def set_alias(self, alias):
    """Set a user-defined identififer for this operator.  Used in optimization and transformation of plans"""
    self.alias = alias

  def shortStr(self):
    """Returns a short string describing the current operator and its
    arguments, but not its children. Consider:
    
       query = "A(x) :- R(x,3)."
       logicalplan = dlog.fromDatalog(query)
       (label, root_op) = logicalplan[0]

       str(root_op) returns "Project($0)[Select($1 = 3)[Scan(R)]]"

       shortStr(root_op) should return "Project($0)" """
    raise NotImplementedError("Operator[%s] must override shortStr()" % self.opname())

  def collectGraph(self, graph=None):
    """Collects the operator graph for a given query. Input parameter graph
    has the format { 'nodes' : list(), 'edges' : list() }, initialized to empty
    lists by default. An input graph will be mutated."""

    # Initialize graph if necessary
    if graph is None:
        graph = { 'nodes' : list(), 'edges' : list() }

    # Cycle detection - continue, but don't re-add this node to the graph
    if id(self) in [id(n) for n in graph['nodes']]:
        return graph

    # Add this node to the graph
    graph['nodes'].append(self)
    # Add all edges
    graph['edges'].extend([(x, self) for x in self.children()])
    for x in self.children():
        # Recursively add children and edges to the graph. This mutates graph
        x.collectGraph(graph)

    # Return the graph
    return graph

  def resolveAttribute(self, ref):
    """Return a tuple of (column_name, type) for a given AttributeRef."""
    assert isinstance(ref, expression.AttributeRef)
    return self.scheme().resolve(ref)

  def is_leaf(self):
    return False

class ZeroaryOperator(Operator):
  """Operator with no arguments"""
  def __init__(self):
    Operator.__init__(self)

  def __eq__(self, other):
    return self.__class__ == other.__class__

  def children(self):
    return []

  def compile(self, resultsym):
    code = self.language.comment("Compiled subplan for %s" % self)
    self.trace("symbol", resultsym)
    if self.bound and self.language.reusescans:
      code += self.language.new_relation_assignment(resultsym, self.bound)     
    else:
      code += "%s" % (self.compileme(resultsym),)
      #code += self.language.comment("Binding: %s" % resultsym)
      self.bound = resultsym
      code += self.compiletrace()
    code += self.language.log("Evaluating subplan %s" % self)
    return code

  def apply(self, f):
    """Apply a function to your children"""
    return self

  def copy(self, other):
    """Deep copy"""
    Operator.copy(self, other)

class UnaryOperator(Operator):
  """Operator with one argument"""
  def __init__(self, input):
    self.input = input
    Operator.__init__(self)

  def __eq__(self, other):
    return self.__class__ == other.__class__ and self.input == other.input
  
  def children(self):
    return [self.input]

  def compile(self, resultsym):
    """Compile this operator to the language specified."""
    #TODO: Why is the language not an argument? 
    code = self.language.comment("Compiled subplan for %s" % self)
    if self.bound:
      code += self.language.assignment(resultsym, self.bound)
    else:
      inputsym = gensym()
      # compile the previous operator
      prev = self.input.compile(inputsym)
      # compile me
      me = self.compileme(resultsym, inputsym)
      code += emit(prev, me)
    code += self.language.log("Evaluating subplan %s" % self)
    return code

  def scheme(self):
    """Default scheme is the same as the input.  Usually overriden"""
    return self.input.scheme()

  def apply(self, f):
    """Apply a function to your children"""
    self.input = f(self.input)
    return self

  def __repr__(self):
    return str(self)

  def copy(self, other):
    """deep copy"""
    self.input = other.input
    Operator.copy(self, other)

class BinaryOperator(Operator):
  """Operator with two arguments"""
  def __init__(self, left, right):
    self.left = left
    self.right = right
    Operator.__init__(self)

  def __eq__(self, other):
    return self.__class__ == other.__class__ and self.left == other.left and self.right == other.right

  def children(self):
    return [self.left, self.right]

  def compile(self, resultsym):
    """Compile this plan.  Result sym is the variable name to use to hold the result of this operator."""
    code = self.language.comment("Compiled subplan for %s" % self)
    code += self.language.log("Evaluating subplan %s" % self)
    #TODO: Why is language not an argument?
    if self.bound:
      code += self.language.assignment(resultsym, self.bound)
    else:
      leftsym = gensym()
      rightsym = gensym()
      code += emit(self.left.compile(leftsym)
                   , self.right.compile(rightsym)
                   , self.compileme(resultsym, leftsym, rightsym))
    return code

  def apply(self, f):
    """Apply a function to your children"""
    self.left = f(self.left)
    self.right = f(self.right)
    return self

  def __repr__(self):
    return str(self)

  def copy(self, other):
    """deep copy"""
    self.left = other.left
    self.right = other.right
    Operator.copy(self, other)

class NaryOperator(Operator):
  """Operator with N arguments.  e.g., multi-way joins in one step."""
  def __init__(self, args):
    self.args = args
    Operator.__init__(self)

  def compile(self, resultsym):
    """Compile this plan.  Result sym is the variable name to use to hold the result of this operator."""
    #TODO: Why is language not an argument?
    code = self.language.comment("Compiled subplan for %s" % self)
    code += self.language.log("Evaluating subplan %s" % self)
    if self.bound:
      code += self.language.assignment(resultsym, self.bound)
    else:
      argsyms = [gensym() for arg in self.args]
      code += emit([arg.compile(sym) for arg,sym in zip(self.args,argsyms)] + [self.compileme(resultsym, argsyms)])
    return code

  def children(self):
    return self.args

  def copy(self, other):
    """deep copy"""
    self.args = [a for a in other.args]
    Operator.copy(self, other)

  def apply(self, f):
    """Apply a function to your children"""
    self.args = [f(arg) for arg in self.args]
    return self

class NaryJoin(NaryOperator):
  def scheme(self):
    sch = scheme.Scheme()
    for arg in self.args:
      sch = sch + arg.scheme()
    return sch


"""Logical Relational Algebra"""

class Union(BinaryOperator):
  def scheme(self): 
    """Same semantics as SQL: Assume first schema "wins" and throw an  error if they don't match during evaluation"""
    return self.left.scheme()

  def shortStr(self):
    return self.opname()

class UnionAll(BinaryOperator):
  """Bag union."""
  def __init__(self, left=None, right=None):
    BinaryOperator.__init__(self, left, right)

  def copy(self, other):
    """deep copy"""
    BinaryOperator.copy(self, other)

  def scheme(self):
    return self.left.scheme()

  def shortStr(self):
    return self.opname()

class Intersection(BinaryOperator):
  """Bag intersection."""
  def scheme(self):
    return self.left.scheme()

  def shortStr(self):
    return self.opname()

class Difference(BinaryOperator):
  """Bag difference"""
  def scheme(self):
    return self.left.scheme()

  def shortStr(self):
    return self.opname()

class CompositeBinaryOperator(BinaryOperator):
  """Join-like operations whose output schema combines its input schemas."""

  def add_equijoin_condition(self, col0, col1):
    """Attempt to add a selection filter to this operation.

    Returns a (possibly modified) operator or None if the columns do not
    refer to different children of the join/cross-product.
    """
    raise NotImplementedException()

  @staticmethod
  def get_equijoin_condition(col0, col1):
    """Return a boolean expression representing an equijoin."""

    return expression.EQ(expression.UnnamedAttributeRef(col0),
                         expression.UnnamedAttributeRef(col1))

class CrossProduct(CompositeBinaryOperator):
  """Logical Cross Product operator"""
  def __init__(self, left=None, right=None):
    BinaryOperator.__init__(self, left, right)

  def copy(self, other):
    """deep copy"""
    BinaryOperator.copy(self, other)

  def shortStr(self):
    return self.opname()

  def scheme(self):
    """Return the scheme of the result."""
    return self.left.scheme() + self.right.scheme()

  def add_equijoin_condition(self, col0, col1):
    """Convert the cross-product into a join whenever possible."""
    condition = self.get_equijoin_condition(col0, col1)
    return Join(condition, self.left, self.right)

class Join(CompositeBinaryOperator):
  """Logical Join operator"""
  def __init__(self, condition=None, left=None, right=None):
    self.condition = condition
    BinaryOperator.__init__(self, left, right)

  def __eq__(self, other):
    return BinaryOperator.__eq__(self,other) and self.condition == other.condition

  def copy(self, other):
    """deep copy"""
    self.condition = other.condition
    BinaryOperator.copy(self, other)

  def shortStr(self):
    return "%s(%s)" % (self.opname(), self.condition)

  def scheme(self):
    """Return the scheme of the result."""
    return self.left.scheme() + self.right.scheme()

  def add_equijoin_condition(self, col0, col1):
    condition = self.get_equijoin_condition(col0, col1)
    self.condition = expression.AND(self.condition, condition)
    return self

class Apply(UnaryOperator):
  def __init__(self, mappings=None, input=None):
    """Create new attributes from expressions with optional rename.

    mappings is a list of tuples of the form:
    (column_name, raco.expression.Expression)

    column_name can be None, in which case the system will infer a name based on
    the expression."""

    def resolve_name(name, sexpr):
      if name:
        return name
      elif isinstance(sexpr ,expression.AttributeRef):
        return input.resolveAttribute(sexpr)[0]
      else:
        return str(sexpr)

    if mappings is not None:
      self.mappings = [(resolve_name(name, sexpr), sexpr) for name, sexpr
                       in mappings]
    UnaryOperator.__init__(self, input)

  def __eq__(self, other):
    return UnaryOperator.__eq__(self,other) and \
      self.expressions == other.expressions

  def copy(self, other):
    """deep copy"""
    self.mappings = other.mappings
    UnaryOperator.copy(self, other)

  def scheme(self):
    """scheme of the result."""
    new_attrs = [(name,expr.typeof()) for (name, expr) in self.mappings]
    return scheme.Scheme(new_attrs)

  def shortStr(self):
    estrs = ",".join(["%s=%s" % (name, str(ex)) for name, ex in self.mappings])
    return "%s(%s)" % (self.opname(), estrs)

#TODO: Non-scheme-mutating operators
class Distinct(UnaryOperator):
  """Remove duplicates from the child operator"""
  def __init__(self, input=None):
    UnaryOperator.__init__(self, input)

  def scheme(self):
    """scheme of the result"""
    return self.input.scheme()

  def shortStr(self):
    return self.opname()

class Limit(UnaryOperator):
  def __init__(self, count=None, input=None):
    UnaryOperator.__init__(self, input)
    self.count = count

  def __eq__(self, other):
    return UnaryOperator.__eq__(self,other) and self.count == other.count

  def copy(self, other):
    self.count = other.count
    UnaryOperator.copy(self, other)

  def scheme(self):
    return self.input.scheme()

  def shortStr(self):
    return "%s(%s)" % (self.opname(), self.count)

class Select(UnaryOperator):
  """Logical selection operator"""
  def __init__(self, condition=None, input=None):
    self.condition = condition
    UnaryOperator.__init__(self, input)

  def __eq__(self, other):
    return UnaryOperator.__eq__(self,other) and self.condition == other.condition

  def shortStr(self):
    if isinstance(self.condition,dict): 
      cond = self.condition["condition"]
    else:
      cond = self.condition
    return "%s(%s)" % (self.opname(), cond)

  def copy(self, other):
    """deep copy"""
    self.condition = other.condition
    UnaryOperator.copy(self, other)

  def scheme(self):
    """scheme of the result."""
    return self.input.scheme()

class Project(UnaryOperator):
  """Logical projection operator"""
  def __init__(self, columnlist=None, input=None):
    self.columnlist = columnlist
    UnaryOperator.__init__(self, input)

  def __eq__(self, other):
    return UnaryOperator.__eq__(self,other) and self.columnlist == other.columnlist 

  def shortStr(self):
    colstring = ",".join([str(x) for x in self.columnlist])
    return "%s(%s)" % (self.opname(), colstring)

  def __repr__(self):
    return "%s" % self

  def copy(self, other):
    """deep copy"""
    self.columnlist = other.columnlist
    UnaryOperator.copy(self, other)

  def scheme(self):
    """scheme of the result. Raises a TypeError if a name in the project list is not in the source schema"""
    # TODO: columnlist should perhaps be a list of column expressions, TBD
    attrs = [self.input.resolveAttribute(attref) for attref in self.columnlist]
    return scheme.Scheme(attrs)

class GroupBy(UnaryOperator):
  """Logical projection operator"""
  def __init__(self, columnlist=None, input=None):
    if not columnlist:
      columnlist = []
    self.columnlist = columnlist

    self.groupinglist = [e for e in self.columnlist if not expression.isaggregate(e)]
    self.aggregatelist = [e for e in self.columnlist if expression.isaggregate(e)]
    UnaryOperator.__init__(self, input)

  def shortStr(self):
    groupstring = ",".join([str(x) for x in self.groupinglist])
    aggstr = ",".join([str(x) for x in self.aggregatelist])
    return "%s(%s; %s)" % (self.opname(), groupstring, aggstr)

  def copy(self, other):
    """deep copy"""
    self.columnlist = other.columnlist
    self.groupinglist = other.groupinglist
    self.aggregatelist = other.aggregatelist
    UnaryOperator.copy(self, other)

  def scheme(self):
    """scheme of the result."""
    def resolve(i, attr):
      if isinstance(attr,expression.AttributeRef):
        return self.input.resolveAttribute(attr)
      else:
        return ("%s%s" % (attr.__class__.__name__,i), attr.typeof())

    attrs = [resolve(i, e) for i, e in enumerate(self.columnlist)]
    return scheme.Scheme(attrs)

class ProjectingJoin(Join):
  """Logical Projecting Join operator"""
  def __init__(self, condition=None, left=None, right=None, columnlist=None):
    self.columnlist = columnlist
    Join.__init__(self, condition, left, right)

  def __eq__(self, other):
    return Join.__eq__(self,other) and self.columnlist == other.columnlist

  def shortStr(self):
    if self.columnlist is None:
      return Join.shortStr(self)
    return "%s(%s; %s)" % (self.opname(), self.condition, self.columnlist)

  def copy(self, other):
    """deep copy"""
    self.columnlist = other.columnlist
    Join.copy(self, other)

  def scheme(self):
    """Return the scheme of the result."""
    if self.columnlist is None:
      return Join.scheme(self)
    combined = self.left.scheme() + self.right.scheme()
    # TODO: columnlist should perhaps be a list of arbitrary column expressions, TBD
    return scheme.Scheme([combined[p.position] for p in self.columnlist])

  def add_equijoin_condition(self, col0, col1):
    # projects are pushed after selections
    raise NotImplementedException()

class Shuffle(UnaryOperator):
  """Send the input to the specified servers"""
  def __init__(self, child=None, columnlist=None):
      UnaryOperator.__init__(self, child)
      self.columnlist = columnlist

  def shortStr(self):
      return "%s(%s)" % (self.opname(), self.columnlist)

  def copy(self, other):
      self.columnlist = other.columnlist
      UnaryOperator.copy(self, other)

class Collect(UnaryOperator):
  """Send input to one server"""
  def __init__(self, child=None, server=None):
      UnaryOperator.__init__(self, child)
      self.server = server

  def shortStr(self):
      return "%s(@%s)" % (self.opname(), self.server)

  def copy(self, other):
      self.server = other.server
      UnaryOperator.copy(self, other)

class Broadcast(UnaryOperator):
  """Send input to all servers"""
  def shortStr(self):
      return self.opname()

class PartitionBy(UnaryOperator):
  """Send input to a server indicated by a hash of specified columns."""
  def __init__(self, columnlist=None, input=None):
    self.columnlist = columnlist
    UnaryOperator.__init__(self, input)

  def __eq__(self, other):
    return UnaryOperator.__eq__(self,other) and self.columnlist == other.columnlist

  def shortStr(self):
    colstring = ",".join([str(x) for x in self.columnlist])
    return "%s(%s)" % (self.opname(), colstring)

  def __repr__(self):
    return str(self)

  def copy(self, other):
    """deep copy"""
    self.columnlist = other.columnlist
    UnaryOperator.copy(self, other)

  def scheme(self):
    """scheme of the result. Raises a TypeError if a name in the project list is not in the source schema"""
    return self.input.scheme()

class Fixpoint(Operator):
  def __init__(self, body=None):
    self.body = body

  def children(self):
    return [self.body]

  def __str__(self):
    return "%s[%s]" % (self.shortStr(), str(self.body))

  def __repr__(self):
    return str(self)

  def shortStr(self):
    return """Fixpoint"""

  def apply(self, f):
    """Apply a function to your children"""
    self.body.apply(f)
    return self
 
  def scheme(self):
    if self.body:
      return self.body.scheme()
    else:
      raise RecursionError("No Scheme defined yet for fixpoint")
 
  def loopBody(self,plan):
    self.body = plan

class State(ZeroaryOperator):
  """A placeholder operator for a recursive plan"""

  def __init__(self, name, fixpoint):
    ZeroaryOperator.__init__(self)
    self.name = name
    self.fixpoint = fixpoint

  def shortStr(self):
    return "%s(%s)" % (self.opname(), self.name)

  def scheme(self):
    return self.fixpoint.scheme()

class Store(UnaryOperator):
  """Store output to a relational table.

  relation_key is a string of the form "program:user:relation".
  """

  def __init__(self, relation_key=None, plan=None):
    UnaryOperator.__init__(self, plan)
    self.relation_key = relation_key

  def shortStr(self):
    return "%s(%s)" % (self.opname(),self.relation_key)

  def copy(self, other):
    self.relation_key = other.relation_key
    UnaryOperator.copy(self, other)

class EmptyRelation(ZeroaryOperator):
  """Relation with no tuples."""

  def __init__(self, _scheme=None):
    self._scheme = _scheme

  def shortStr(self):
    return "%s(%s)" % (self.opname(), self._scheme)

  def copy(self, other):
    """deep copy"""
    self._scheme = other._scheme

  def scheme(self):
    """scheme of the result."""
    return self._scheme

class SingletonRelation(ZeroaryOperator):
  """Relation with a single empty tuple.

  Used for constructing table literals.
  """

  def shortStr(self):
    return "SingletonRelation"

  def copy(self, other):
    """deep copy"""
    pass

  def scheme(self):
    """scheme of the result."""
    return scheme.Scheme()

class Scan(ZeroaryOperator):
  """Logical Scan operator."""

  def __init__(self, relation_key=None, _scheme=None):
    """Initalize a scan operator.

    relation_key is a string of the form "user:program:relation"
    scheme is the schema of the relation.
    """
    self.relation_key = relation_key
    self._scheme = _scheme
    ZeroaryOperator.__init__(self)

  def __eq__(self,other):
    return ZeroaryOperator.__eq__(self,other) and \
      self.relation_key == other.relation_key and \
      self.scheme() == other.scheme()

  def shortStr(self):
    return "%s(%s)" % (self.opname(), self.relation_key)

  def __repr__(self):
    return str(self)

  def copy(self, other):
    """deep copy"""
    self.relation_key = other.relation_key
    self._scheme = other._scheme

    # TODO: need a cleaner and more general way of tracing information through 
    # the compilation process for debugging purposes
    if hasattr(other, "originalterm"):
      self.originalterm = other.originalterm
    ZeroaryOperator.copy(self, other)

  def scheme(self):
    """Scheme of the result, which is just the scheme of the relation."""
    return self._scheme

  def is_leaf(self):
    return True

class StoreTemp(UnaryOperator):
  """Store an input relation to a "temporary" relation.

  Temporary relations exist for the lifetime of a query.
  """
  def __init__(self, name=None, input=None):
    UnaryOperator.__init__(self, input)
    self.name = name

  def shortStr(self):
    return 'StoreTemp(%s)' % self.name

  def copy(self, other):
    self.name = other.name
    UnaryOperator.copy(self, other)

  def __eq__(self, other):
    return UnaryOperator.__eq__(self,other) and self.name == other.name

class ScanTemp(ZeroaryOperator):
  """Read the contents of a temporary relation."""

  def __init__(self, name=None, _scheme=None):
    self.name = name
    self._scheme = _scheme
    ZeroaryOperator.__init__(self)

  def __eq__(self,other):
    return ZeroaryOperator.__eq__(self,other) and self.name == other.name \
      and self._scheme == other._scheme

  def shortStr(self):
    return "%s(%s,%s)" % (self.opname(), self.name, str(self._scheme))

  def copy(self, other):
    self.name = other.name
    self._scheme = other._scheme
    ZeroaryOperator.copy(self, other)

  def scheme(self):
    return self._scheme

  def is_leaf(self):
    return True

class Sequence(NaryOperator):
  """Execute a sequence of plans in serial order."""
  def __init__(self, ops):
    NaryOperator.__init__(self, ops)

  def shortStr(self):
    return self.opname()


class DoWhile(BinaryOperator):
  def __init__(self, body_op, term_op):
    """Repeatedly execute a sequence of plans until a termination condtion.

    body_op is an operation with no output.

    term_op is an operation that should map to a single row, single column
    relation.  The loop continues if its value is True.
    """
    BinaryOperator.__init__(self, body_op, term_op)

  def shortStr(self):
    return self.opname()

def attribute_references(condition):
  """Generates a list of attributes referenced in the condition"""
  if isinstance(condition, BinaryBooleanOperator):
    for a in attribute_references(condition.left): yield a
    for a in attribute_references(condition.right): yield a
  elif isinstance(condition, Attribute):
    yield condition.name
"""
#def coveredby(

class PushSelect(Rule):
  def fire(self, expr):
    if isinstance(expr, Select):
      if isinstance(expr.input, Join):
        join = expr.input
        select = expr
        if join.left.scheme().contains(attributes):
          # push left
        if join.right.scheme().contains(attributes):
          # push right
"""     

class LogicalAlgebra:
  operators = [
  Join,
  Select,
  Scan
]
  rules = []


