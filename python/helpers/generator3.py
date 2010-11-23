# encoding: utf-8
"""
This thing tries to restore public interface of objects that don't have a python
source: C extensions and built-in objects. It does not reimplement the
'inspect' module, but complements it.

Since built-ins don't have many features that full-blown objects have, 
we do not support some fancier things like metaclasses.

We use certain kind of doc comments ("f(int) -> list") as a hint for functions'
input and output, especially in builtin functions.

This code has to work with CPython versions from 2.2 to 3.0+, and hopefully with
compatible versions of Jython and IronPython.

NOTE: Currently python 3 support is outright BROKEN, because bare asterisks and param decorators
are not parsed. This is deliberate in current version, since the rest of PyCharm does not support
all this too.
"""

from datetime import datetime

OUR_OWN_DATETIME = datetime(2010, 11, 4, 13, 40, 45) # datetime.now() of edit time
# we could use script's ctime, but the actual running copy may have it all wrong.
#
# Note: DON'T FORGET TO UPDATE!

import sys
import os
import string
import types
import atexit
import keyword

try:
    import inspect
except:
    inspect = None # it may fail

import re

if sys.platform == 'cli':
    import clr

version = (
    (sys.hexversion & (0xff << 24)) >> 24,
    (sys.hexversion & (0xff << 16)) >> 16
)

if version[0] >= 3:
    import builtins as the_builtins

    string = "".__class__
    #LETTERS = string_mod.ascii_letters
    STR_TYPES = (getattr(the_builtins, "bytes"), str)

    NUM_TYPES = (int, float)
    SIMPLEST_TYPES = NUM_TYPES + STR_TYPES + (None.__class__,)
    EASY_TYPES = NUM_TYPES + STR_TYPES + (None.__class__, dict, tuple, list)

    def the_exec(source, context):
        exec(source, context)

else: # < 3.0
    import __builtin__ as the_builtins
    #LETTERS = string_mod.letters
    STR_TYPES = (getattr(the_builtins, "unicode"), str)

    NUM_TYPES = (int, long, float)
    SIMPLEST_TYPES = NUM_TYPES + STR_TYPES + (types.NoneType,)
    EASY_TYPES = NUM_TYPES + STR_TYPES + (types.NoneType, dict, tuple, list)

    def the_exec(source, context):
        exec (source) in context

BUILTIN_MOD_NAME = the_builtins.__name__

if version[0] == 2 and version[1] < 4:
    HAS_DECORATORS = False

    def lstrip(s, prefix):
        i = 0
        while s[i] == prefix:
            i += 1
        return s[i:]

else:
    HAS_DECORATORS = True
    lstrip = string.lstrip

#
IDENT_PATTERN = "[A-Za-z_][0-9A-Za-z_]*" # re pattern for identifier
NUM_IDENT_PATTERN = re.compile("([A-Za-z_]+)[0-9]?[A-Za-z_]*") # 'foo_123' -> $1 = 'foo_'
STR_CHAR_PATTERN = "[0-9A-Za-z_.,\+\-&\*% ]"

DOC_FUNC_RE = re.compile("(?:.*\.)?(\w+)\(([^\)]*)\).*") # $1 = function name, $2 = arglist

SANE_REPR_RE = re.compile(IDENT_PATTERN + "(?:\(.*\))?") # identifier with possible (...), go catches

IDENT_RE = re.compile("(" + IDENT_PATTERN + ")") # $1 = identifier

STARS_IDENT_RE = re.compile("(\*?\*?" + IDENT_PATTERN + ")") # $1 = identifier, maybe with a * or **

IDENT_EQ_RE = re.compile("(" + IDENT_PATTERN + "\s*=)") # $1 = identifier with a following '='

SIMPLE_VALUE_RE = re.compile(
    "(\([+-]?[0-9](?:\s*,\s*[+-]?[0-9])*\))|" + # a numeric tuple, e.g. in pygame
    "([+-]?[0-9]+\.?[0-9]*(?:[Ee]?[+-]?[0-9]+\.?[0-9]*)?)|" + # number
    "('" + STR_CHAR_PATTERN + "*')|" + # single-quoted string
    '("' + STR_CHAR_PATTERN + '*")|' + # double-quoted string
    "(\[\])|" +
    "(\{\})|" +
    "(\(\))|" +
    "(True|False|None)"
) # $? = sane default value

def _searchbases(cls, accum):
# logic copied from inspect.py
    if cls not in accum:
        accum.append(cls)
        for x in cls.__bases__:
            _searchbases(x, accum)

def getMRO(a_class):
# logic copied from inspect.py
    "Returns a tuple of MRO classes."
    if hasattr(a_class, "__mro__"):
        return a_class.__mro__
    elif hasattr(a_class, "__bases__"):
        bases = []
        _searchbases(a_class, bases)
        return tuple(bases)
    else:
        return tuple()


def getBases(a_class): # TODO: test for classes that don't fit this scheme
    "Returns a sequence of class's bases."
    if hasattr(a_class, "__bases__"):
        return a_class.__bases__
    else:
        return ()


def isCallable(x):
    return hasattr(x, '__call__')


def sortedNoCase(p_array):
    "Sort an array case insensitevely, returns a sorted copy"
    p_array = list(p_array)
    if version[0] < 3:
        def c(x, y):
            x = x.upper()
            y = y.upper()
            if x > y:
                return 1
            elif x < y:
                return -1
            else:
                return 0

        p_array.sort(c)
    else:
        p_array.sort(key=lambda x: x.upper())

    return p_array

def cleanup(value):
    # TODO: a possible perf hog, rewrite using a list of larger chunks
    result = ''
    for c in value:
        if c == '\n': result += '\\n'
        elif c == '\r': result += '\\r'
        elif c < ' ' or c > chr(127): result += '?'
        else: result += c
    return result

# http://blogs.msdn.com/curth/archive/2009/03/29/an-ironpython-profiler.aspx
def print_profile():
    data = []
    data.extend(clr.GetProfilerData())
    data.sort(lambda x, y: -cmp(x.ExclusiveTime, y.ExclusiveTime))
    for p in data:
        print('%s\t%d\t%d\t%d' % (p.Name, p.InclusiveTime, p.ExclusiveTime, p.Calls))

def is_clr_type(t):
    if not t: return False
    try:
        clr.GetClrType(t)
        return True
    except TypeError:
        return False

_prop_types = [type(property())]
try: _prop_types.append(types.GetSetDescriptorType)
except: pass

try: _prop_types.append(types.MemberDescriptorType)
except: pass

_prop_types = tuple(_prop_types)

def isProperty(x):
    return isinstance(x, _prop_types)

FAKE_CLASSOBJ_NAME = "___Classobj"

def sanitizeIdent(x):
    "Takes an identifier and returns it sanitized"
    if x in ("class", "object", "def", "list", "tuple", "int", "float", "str", "unicode" "None"):
        return "p_" + x
    else:
        return x.replace("-", "_").replace(" ", "_").replace(".", "_") # for things like "list-or-tuple" or "list or tuple"

def reliable_repr(value):
    # some subclasses of built-in types (see PyGtk) may provide invalid __repr__ implementations,
    # so we need to sanitize the output
    if isinstance(value, bool):
        return repr(bool(value))
    for t in NUM_TYPES:
        if isinstance(value, t):
            return repr(t(value))
    return repr(value)

def sanitizeValue(p_value):
    "Returns p_value or its part if it represents a sane simple value, else returns 'None'"
    if isinstance(p_value, STR_TYPES):
        match = SIMPLE_VALUE_RE.match(p_value)
        if match:
            return match.groups()[match.lastindex - 1]
        else:
            return 'None'
    elif isinstance(p_value, NUM_TYPES):
        return reliable_repr(p_value)
    elif p_value is None:
        return 'None'
    else:
        if hasattr(p_value, "__name__") and hasattr(p_value, "__module__") and p_value.__module__ == BUILTIN_MOD_NAME:
            return p_value.__name__ # float -> "float"
        else:
            return repr(repr(p_value)) # function -> "<function ...>", etc

def extractAlphaPrefix(p_string, default="some"):
    "Returns 'foo' for things like 'foo1' or 'foo2'; if prefix cannot be found, the default is returned"
    match = NUM_IDENT_PATTERN.match(p_string)
    name = match and match.groups()[match.lastindex - 1] or None
    return name or default


class FakeClassObj:
    "A mock class representing the old style class base."
    __module__ = None
    __class__ = None

    def __init__(self):
        pass

if version[0] < 3:
    from pyparsing import *
else:
    from pyparsing_py3 import *

# grammar to parse parameter lists

# // snatched from parsePythonValue.py, from pyparsing samples, copyright 2006 by Paul McGuire but under BSD license.
# we don't suppress lots of punctuation because we want it back when we reconstruct the lists

lparen, rparen, lbrack, rbrack, lbrace, rbrace, colon = map(Literal, "()[]{}:")

integer = Combine(Optional(oneOf("+ -")) + Word(nums))\
    .setName("integer")
real = Combine(Optional(oneOf("+ -")) + Word(nums) + "." +
               Optional(Word(nums)) +
               Optional(oneOf("e E")+Optional(oneOf("+ -")) +Word(nums)))\
    .setName("real")
tupleStr = Forward()
listStr = Forward()
dictStr = Forward()

boolLiteral = oneOf("True False")
noneLiteral = Literal("None")

listItem = real|integer|quotedString|unicodeString|boolLiteral|noneLiteral| \
            Group(listStr) | tupleStr | dictStr

tupleStr << ( Suppress("(") + Optional(delimitedList(listItem)) +
              Optional(Literal(",")) + Suppress(")") ).setResultsName("tuple")

listStr << (lbrack + Optional(delimitedList(listItem) +
                              Optional(Literal(","))) + rbrack).setResultsName("list")

dictEntry = Group(listItem + colon + listItem)
dictStr << (lbrace + Optional(delimitedList(dictEntry) + Optional(Literal(","))) + rbrace).setResultsName("dict")
# \\ end of the snatched part

# our output format is s-expressions:
# (simple name optional_value) is name or name=value
# (nested (simple ...) (simple ...)) is (name, name,...)
# (opt ...) is [, ...] or suchlike.

T_SIMPLE = 'Simple'
T_NESTED = 'Nested'
T_OPTIONAL = 'Opt'
T_RETURN = "Ret"

TRIPLE_DOT = '...'

COMMA = Suppress(",")
APOS = Suppress("'")
QUOTE = Suppress('"')
SP = Suppress(Optional(White()))

ident = Word(alphas + "_", alphanums + "_-.").setName("ident") # we accept things like "foo-or-bar"
decorated_ident = ident + Optional(Suppress(SP + Literal(":") + SP + ident)) # accept "foo: bar", ignore "bar"
spaced_ident = Combine(decorated_ident + ZeroOrMore(Literal(' ') + decorated_ident)) # we accept 'list or tuple' or 'C struct'

# allow quoted names, because __setattr__, etc docs use it
paramname = spaced_ident | \
            APOS + spaced_ident + APOS | \
            QUOTE + spaced_ident + QUOTE

parenthesized_tuple = ( Literal("(") + Optional(delimitedList(listItem, combine=True)) +
              Optional(Literal(",")) + Literal(")") ).setResultsName("(tuple)")


initializer = (SP + Suppress("=") + SP + Combine(parenthesized_tuple | listItem | ident )).setName("=init") # accept foo=defaultfoo

param = Group(Empty().setParseAction(replaceWith(T_SIMPLE)) + Combine(Optional(oneOf("* **")) + paramname) + Optional(initializer))

ellipsis = Group(
        Empty().setParseAction(replaceWith(T_SIMPLE))+ \
  (Literal("..") + \
  ZeroOrMore(Literal('.'))).setParseAction(replaceWith(TRIPLE_DOT)) # we want to accept both 'foo,..' and 'foo, ...'
        )

paramSlot = Forward()

simpleParamSeq = ZeroOrMore(paramSlot + COMMA) + Optional(paramSlot + Optional(COMMA))
nestedParamSeq = Group(
        Suppress('(').setParseAction(replaceWith(T_NESTED)) + \
  simpleParamSeq + Optional(ellipsis + Optional(COMMA) + Optional(simpleParamSeq)) + \
  Suppress(')')
        ) # we accept "(a1, ... an)"

paramSlot << (param | nestedParamSeq)

optionalPart = Forward()

paramSeq = simpleParamSeq + Optional(optionalPart) # this is our approximate target 

optionalPart << (
Group(
    Suppress('[').setParseAction(replaceWith(T_OPTIONAL)) + Optional(COMMA) + \
    paramSeq + Optional(ellipsis) + \
    Suppress(']')
  ) \
  | ellipsis
)

return_type = Group(
  Empty().setParseAction(replaceWith(T_RETURN)) +
  Suppress(SP + (Literal("->") | (Literal(":") + SP + Literal("return"))) + SP) +
  ident
)

# this is our ideal target, with balancing paren and a multiline rest of doc.
paramSeqAndRest = paramSeq + Suppress(')') + Optional(return_type) + Suppress(Optional(Regex(".*(?s)")))

def transformSeq(results, toplevel=True):
    "Transforms a tree of ParseResults into a param spec string."
    ret = [] # add here token to join
    for token in results:
        token_type = token[0]
        if token_type is T_SIMPLE:
            token_name = token[1]
            if len(token) == 3: # name with value
                if toplevel:
                    ret.append(sanitizeIdent(token_name) + "=" + sanitizeValue(token[2]))
                else:
                # smth like "a, (b1=1, b2=2)", make it "a, p_b"
                    return ["p_" + results[0][1]] # NOTE: fishy. investigate.
            elif token_name == TRIPLE_DOT:
                if toplevel and not hasItemStartingWith(ret, "*"):
                    ret.append("*more")
                else:
                # we're in a "foo, (bar1, bar2, ...)"; make it "foo, bar_tuple"
                    return extractAlphaPrefix(results[0][1]) + "_tuple"
            else: # just name
                ret.append(sanitizeIdent(token_name))
        elif token_type is T_NESTED:
            ret.append(transformSeq(token[1:], False))
        elif token_type is T_OPTIONAL:
            ret.extend(transformOptionalSeq(token))
        elif token_type is T_RETURN:
            pass # this is handled elsewhere
        else:
            raise Exception("This cannot be a token type: " + repr(token_type))
    return ret

def transformOptionalSeq(results):
    """
    Produces a string that describes the optional part of parameters.
    @param results must start from T_OPTIONAL.
    """
    assert results[0] is T_OPTIONAL, "transformOptionalSeq expects a T_OPTIONAL node, sees " + repr(results[0])
    ret = []
    for token in results[1:]:
        token_type = token[0]
        if token_type is T_SIMPLE:
            token_name = token[1]
            if len(token) == 3: # name with value; little sense, but can happen in a deeply nested optional
                ret.append(sanitizeIdent(token_name) + "=" + sanitizeValue(token[2]))
            elif token_name == '...':
            # we're in a "foo, [bar, ...]"; make it "foo, *bar"
                return ["*" + extractAlphaPrefix(results[1][1])] # we must return a seq; [1] is first simple, [1][1] is its name
            else: # just name
                ret.append(sanitizeIdent(token_name) + "=None")
        elif token_type is T_OPTIONAL:
            ret.extend(transformOptionalSeq(token))
        # maybe handle T_NESTED if such cases ever occur in real life
        # it can't be nested in a sane case, really
    return ret

def flatten(seq):
    "Transforms tree lists like ['a', ['b', 'c'], 'd'] to strings like '(a, (b, c), d)', enclosing each tree level in parens."
    ret = []
    for one in seq:
        if type(one) is list:
            ret.append(flatten(one))
        else:
            ret.append(one)
    return "(" + ", ".join(ret) + ")"

def makeNamesUnique(seq, name_map=None):
    """
    Returns a copy of tree list seq where all clashing names are modified by numeric suffixes:
    ['a', 'b', 'a', 'b'] becomes ['a', 'b', 'a_1', 'b_1'].
    Each repeating name has its own counter in the name_map.
    """
    ret = []
    if not name_map:
        name_map = {}
    for one in seq:
        if type(one) is list:
            ret.append(makeNamesUnique(one, name_map))
        else:
            one_key = lstrip(one, "*") # starred parameters are unique sans stars
            if one_key in name_map:
                old_one = one_key
                one = one + "_" + str(name_map[old_one])
                name_map[old_one] += 1
            else:
                name_map[one_key] = 1
            ret.append(one)
    return ret

def hasItemStartingWith(p_seq, p_start):
    for item in p_seq:
        if isinstance(item, STR_TYPES) and item.startswith(p_start):
            return True
    return False

# return type inference helper table
INT_LIT =  '0'
FLOAT_LIT ='0.0'
DICT_LIT = '{}'
LIST_LIT = '[]'
TUPLE_LIT ='()'
BOOL_LIT = 'False'
RET_TYPE = { # {'type_name': 'value_string'} lookup table
    # int
    "int":      INT_LIT,
    "Int":      INT_LIT,
    "integer":  INT_LIT,
    "Integer":  INT_LIT,
    "short":    INT_LIT,
    "long":     INT_LIT,
    "number":   INT_LIT,
    "Number":   INT_LIT,
    # float
    "float":    FLOAT_LIT,
    "Float":    FLOAT_LIT,
    "double":   FLOAT_LIT,
    "Double":   FLOAT_LIT,
    "floating": FLOAT_LIT,
    # boolean
    "bool":     BOOL_LIT,
    "boolean":  BOOL_LIT,
    "Bool":     BOOL_LIT,
    "Boolean":  BOOL_LIT,
    # list
    'list': LIST_LIT,
    'List': LIST_LIT,
    '[]':   LIST_LIT,
    # tuple
    "tuple":    TUPLE_LIT,
    "sequence": TUPLE_LIT,
    "Sequence": TUPLE_LIT,
    # dict
    "dict":       DICT_LIT,
    "Dict":       DICT_LIT,
    "dictionary": DICT_LIT,
    "Dictionary": DICT_LIT,
    "map":        DICT_LIT,
    "Map":        DICT_LIT,
    "hashtable":  DICT_LIT,
    "Hashtable":  DICT_LIT,
    "{}":         DICT_LIT,
    # "object"
    "object":     "object()"
}
if version[1] < 3:
    UNICODE_LIT = 'u""'
    BYTES_LIT = '""'
    RET_TYPE.update({
        'string':   BYTES_LIT,
        'String':   BYTES_LIT,
        'str':      BYTES_LIT,
        'Str':      BYTES_LIT,
        'character':BYTES_LIT,
        'char':     BYTES_LIT,
        'unicode':  UNICODE_LIT,
        'Unicode':  UNICODE_LIT,
        'bytes':    BYTES_LIT,
        'byte':     BYTES_LIT,
        'Bytes':    BYTES_LIT,
        'Byte':     BYTES_LIT,
    })
    DEFAULT_STR_LIT = BYTES_LIT
else:
    UNICODE_LIT = '""'
    BYTES_LIT = 'b""'
    RET_TYPE.update({
        'string':   UNICODE_LIT,
        'String':   UNICODE_LIT,
        'str':      UNICODE_LIT,
        'Str':      UNICODE_LIT,
        'character':UNICODE_LIT,
        'char':     UNICODE_LIT,
        'unicode':  UNICODE_LIT,
        'Unicode':  UNICODE_LIT,
        'bytes':    BYTES_LIT,
        'byte':     BYTES_LIT,
        'Bytes':    BYTES_LIT,
        'Byte':     BYTES_LIT,
    })
    DEFAULT_STR_LIT = UNICODE_LIT



class ModuleRedeclarator(object):
    def __init__(self, module, outfile, indent_size=4, doing_builtins=False):
        """
        Create new instance.
        @param module module to restore.
        @param outfile output file, must be open and writable.
        @param indent_size amount of space characters per indent
        """
        self.module = module
        self.outfile = outfile
        self.indent_size = indent_size
        self._indent_step = " " * indent_size
        self.imported_modules = {"": the_builtins}
        self._defined = {} # contains True for every name defined so far
        self.doing_builtins = doing_builtins


    def indent(self, level):
        "Return indentation whitespace for given level."
        return self._indent_step * level


    def out(self, what, indent=0):
        "Output the argument, indenting as nedded, and adding a eol"
        self.outfile.write(self.indent(indent))
        self.outfile.write(what)
        self.outfile.write("\n")

    def outDocstring(self, docstring, indent):
        if isinstance(docstring, str):
            lines = docstring.strip().split("\n")
            if lines:
                if len(lines) == 1:
                    self.out('""" ' + lines[0] + ' """', indent)
                else:
                    self.out('"""', indent)
                    for line in lines:
                        self.out(line, indent)
                    self.out('"""', indent)

    def outDocAttr(self, p_object, indent, p_class=None):
        the_doc = p_object.__doc__
        if the_doc:
            if p_class and the_doc == object.__init__.__doc__ and p_object is not object.__init__ and p_class.__doc__:
                the_doc = str(p_class.__doc__) # replace stock init's doc with class's; make it a certain string.
                the_doc += "\n# (copied from class doc)"
            self.outDocstring(the_doc, indent)
        else:
            self.out("# no doc", indent)

    # Some values are known to be of no use in source and needs to be suppressed.
    # Dict is keyed by module names, with "*" meaning "any module";
    # values are lists of names of members whose value must be pruned.
    SKIP_VALUE_IN_MODULE = {
        "sys": (
            "modules", "path_importer_cache", "argv", "builtins",
            "last_traceback", "last_type", "last_value", "builtin_module_names",
        ),
        "posix": (
            "environ",
        ),
        "zipimport": (
            "_zip_directory_cache",
        ),
        "*":   (BUILTIN_MOD_NAME,)
    }

    # {"module": ("name",..)}: omit the names from the skeleton at all.
    OMIT_NAME_IN_MODULE = {}

    if version[0] >= 3:
        v = OMIT_NAME_IN_MODULE.get(BUILTIN_MOD_NAME, []) + ["True", "False", "None", "__debug__"]
        OMIT_NAME_IN_MODULE[BUILTIN_MOD_NAME] = v

    ADD_VALUE_IN_MODULE = {
        "sys": ("exc_value = Exception()", "exc_traceback=None"), # only present after an exception in current thread
    }

    # Some values are special and are better represented by hand-crafted constructs.
    # Dict is keyed by (module name, member name) and value is the replacement.
    REPLACE_MODULE_VALUES = {
        ("numpy.core.multiarray", "typeinfo") : "{}",
    }
    if version[0] <= 2:
        REPLACE_MODULE_VALUES[(BUILTIN_MOD_NAME, "None")] = "object()"
        for std_file in ("stdin", "stdout", "stderr"):
            REPLACE_MODULE_VALUES[("sys", std_file)] = "file('')" #

    # Some functions and methods of some builtin classes have special signatures.
    # {("class", "method"): ("signature_string")}
    PREDEFINED_BUILTIN_SIGS = {
        ("type", "__init__"): "(cls, what, bases=None, dict=None)", # two sigs squeezed into one
        ("object", "__init__"): "(self)",
        ("object", "__new__"): "(cls, *more)", # only for the sake of parameter names readability
        ("object", "__subclasshook__"): "(cls, subclass)", # trusting PY-1818 on sig
        ("int", "__init__"): "(self, x, base=10)", # overrides a fake
        ("list", "__init__"): "(self, seq=())",
        ("tuple", "__init__"): "(self, seq=())", # overrides a fake
        ("set", "__init__"): "(self, seq=())",
        ("dict", "__init__"): "(self, seq=None, **kwargs)",
        ("property", "__init__"): "(self, fget=None, fset=None, fdel=None, doc=None)", # TODO: infer, doc comments have it
        ("dict", "update"): "(self, E=None, **F)", # docstring nearly lies
        (None, "zip"): "(seq1, seq2, *more_seqs)",
        (None, "range"): "(start=None, stop=None, step=None)", # suboptimal: allows empty arglist
        (None, "filter"): "(function_or_none, sequence)",
        (None, "iter"): "(source, sentinel=None)",
        ('frozenset', "__init__"): "(seq=())",
    }

    if version[0] < 3:
        PREDEFINED_BUILTIN_SIGS[("unicode", "__init__")] = "(self, x, encoding=None, errors='strict')" # overrides a fake
        PREDEFINED_BUILTIN_SIGS[("super", "__init__")] = "(self, type1, type2=None)"
        PREDEFINED_BUILTIN_SIGS[(None, "min")] = "(*args, **kwargs)" # too permissive, but py2.x won't allow a better sig
        PREDEFINED_BUILTIN_SIGS[(None, "max")] = "(*args, **kwargs)"
        PREDEFINED_BUILTIN_SIGS[("str", "__init__")] = "(self, x)" # overrides a fake
    else:
        PREDEFINED_BUILTIN_SIGS[("super", "__init__")] = "(self, type1=None, type2=None)"
        PREDEFINED_BUILTIN_SIGS[(None, "min")] = "(*args, key=None)"
        PREDEFINED_BUILTIN_SIGS[(None, "max")] = "(*args, key=None)"
        PREDEFINED_BUILTIN_SIGS[(None, "open")] = "(file, mode='r', buffering=None, encoding=None, errors=None, newline=None, closefd=True)"
        PREDEFINED_BUILTIN_SIGS[("str", "__init__")] = "(self, value, encoding=None, errors='strict')" # overrides a fake
        PREDEFINED_BUILTIN_SIGS[("bytes", "__init__")] = "(self, value, encoding=None, errors='strict')" # overrides a fake

    if version == (2, 5):
        PREDEFINED_BUILTIN_SIGS[("unicode", "splitlines")] = "(keepends=None)" # a typo in docstring there

    # NOTE: per-module signature data may be lazily imported
    # keyed by (module_name, class_name, method_name). PREDEFINED_BUILTIN_SIGS might be a layer of it.
    # value is ("signature", "return_literal")
    PREDEFINED_MOD_CLASS_SIGS = {
        ("binascii", None, "hexlify"): ("(data)", BYTES_LIT),
        ("binascii", None, "unhexlify"): ("(hexstr)", BYTES_LIT),

        ("time", None, "ctime"): ("(seconds=None)", DEFAULT_STR_LIT),

        ("datetime", "date", "__new__"): ("(cls, year=None, month=None, day=None)", None),
        ("datetime", "date", "fromordinal"): ("(cls, ordinal)", "date(1,1,1)"),
        ("datetime", "date", "fromtimestamp"): ("(cls, timestamp)", "date(1,1,1)"),
        ("datetime", "date", "isocalendar"): ("(self)", "(1, 1, 1)"),
        ("datetime", "date", "isoformat"): ("(self)", DEFAULT_STR_LIT),
        ("datetime", "date", "isoweekday"): ("(self)", INT_LIT),
        ("datetime", "date", "replace"): ("(self, year=None, month=None, day=None)", "date(1,1,1)"),
        ("datetime", "date", "strftime"): ("(self, format)", DEFAULT_STR_LIT),
        ("datetime", "date", "timetuple"): ("(self)", "(0, 0, 0, 0, 0, 0, 0, 0, 0)"),
        ("datetime", "date", "today"): ("(self)", "date(1, 1, 1)"),
        ("datetime", "date", "toordinal"): ("(self)", INT_LIT),
        ("datetime", "date", "weekday"): ("(self)", INT_LIT),
        ("datetime", "timedelta", "__new__"
        ): ("(cls, days=None, seconds=None, microseconds=None, milliseconds=None, minutes=None, hours=None, weeks=None)", None),
        ("datetime", "datetime", "__new__"
        ): ("(cls, year=None, month=None, day=None, hour=None, minute=None, second=None, microsecond=None, tzinfo=None)", None),
        ("datetime", "datetime", "astimezone"): ("(self, tz)", "datetime(1, 1, 1)"),
        ("datetime", "datetime", "combine"): ("(cls, date, time)", "datetime(1, 1, 1)"),
        ("datetime", "datetime", "date"): ("(self)", "datetime(1, 1, 1)"),
        ("datetime", "datetime", "fromtimestamp"): ("(cls, timestamp, tz=None)", "datetime(1, 1, 1)"),
        ("datetime", "datetime", "isoformat"): ("(self, sep='T')", DEFAULT_STR_LIT),
        ("datetime", "datetime", "now"): ("(cls, tz=None)", "datetime(1, 1, 1)"),
        ("datetime", "datetime", "strptime"): ("(cls, date_string, format)", DEFAULT_STR_LIT),
        ("datetime", "datetime", "replace" ):
          ("(self, year=None, month=None, day=None, hour=None, minute=None, second=None, microsecond=None, tzinfo=None)", "datetime(1, 1, 1)"),
        ("datetime", "datetime", "time"): ("(self)", "time(0, 0)"),
        ("datetime", "datetime", "timetuple"): ("(self)", "(0, 0, 0, 0, 0, 0, 0, 0, 0)"),
        ("datetime", "datetime", "timetz"): ("(self)", "time(0, 0)"),
        ("datetime", "datetime", "utcfromtimestamp"): ("(self, timestamp)", "datetime(1, 1, 1)"),
        ("datetime", "datetime", "utcnow"): ("(cls)", "datetime(1, 1, 1)"),
        ("datetime", "datetime", "utctimetuple"): ("(self)", "(0, 0, 0, 0, 0, 0, 0, 0, 0)"),
        ("datetime", "time", "__new__"): ("(cls, hour=None, minute=None, second=None, microsecond=None, tzinfo=None)", None),
        ("datetime", "time", "isoformat"): ("(self)", DEFAULT_STR_LIT),
        ("datetime", "time", "replace"): ("(self, hour=None, minute=None, second=None, microsecond=None, tzinfo=None)", "time(0, 0)"),
        ("datetime", "time", "strftime"): ("(self, format)", DEFAULT_STR_LIT),
        ("datetime", "tzinfo", "dst"): ("(self, date_time)", INT_LIT),
        ("datetime", "tzinfo", "fromutc"): ("(self, date_time)", "datetime(1, 1, 1)"),
        ("datetime", "tzinfo", "tzname"): ("(self, date_time)", DEFAULT_STR_LIT),
        ("datetime", "tzinfo", "utcoffset"): ("(self, date_time)", INT_LIT),

        # NOTE: here we stand on shaky ground providing sigs for 3rd-party modules, though well-known
        ("numpy.core.multiarray", "ndarray", "__array__") : ("(self, dtype=None)", None),
        ("numpy.core.multiarray", None, "arange") : ("(start=None, stop=None, step=None, dtype=None)", None), # same as range()
        ("numpy.core.multiarray", None, "set_numeric_ops") : ("(**ops)", None),
    }

    # known properties of modules
    # {{"module": {"class", "property" : ("letters", "getter")}},
    # where letters is any set of r,w,d (read, write, del) and "getter" is a source of typed getter.
    # if vlue is None, the property should be omitted.
    # read-only properties that return an object are not listed.
    G_OBJECT = "lambda self: object()"
    G_TYPE = "lambda self: type(object)"
    G_DICT = "lambda self: {}"
    G_STR = "lambda self: ''"
    G_TUPLE = "lambda self: tuple()"
    G_FLOAT = "lambda self: 0.0"
    G_INT = "lambda self: 0"
    G_BOOL = "lambda self: True"

    KNOWN_PROPS = {
        BUILTIN_MOD_NAME: {
            ("object", '__class__'): ('r', G_TYPE),
            ("BaseException", '__dict__'): ('r', G_DICT),
            ("BaseException", 'message'): ('rwd', G_STR),
            ("BaseException", 'args'): ('r', G_TUPLE),
            ('complex', 'real'): ('r', G_FLOAT),
            ('complex', 'imag'): ('r', G_FLOAT),
            ("EnvironmentError", 'errno'): ('rwd', G_INT),
            ("EnvironmentError", 'message'): ('rwd', G_STR),
            ("EnvironmentError", 'strerror'): ('rwd', G_INT),
            ("EnvironmentError", 'filename'): ('rwd', G_STR),
            ("file", 'softspace'): ('r', G_BOOL),
            ("file", 'name'): ('r', G_STR),
            ("file", 'encoding'): ('r', G_STR),
            ("file", 'mode'): ('r', G_STR),
            ("file", 'closed'): ('r', G_BOOL),
            ("file", 'newlines'): ('r', G_STR),
            ("SyntaxError", 'text'): ('rwd', G_STR),
            ("SyntaxError", 'print_file_and_line'): ('rwd', G_BOOL),
            ("SyntaxError", 'filename'): ('rwd', G_STR),
            ("SyntaxError", 'lineno'): ('rwd', G_INT),
            ("SyntaxError", 'offset'): ('rwd', G_INT),
            ("SyntaxError", 'msg'): ('rwd', G_STR),
            ("SyntaxError", 'message'): ('rwd', G_STR),
            ("slice", 'start'): ('r', G_INT),
            ("slice", 'step'): ('r', G_INT),
            ("slice", 'stop'): ('r', G_INT),
            ("super", '__thisclass__'): ('r', G_TYPE),
            ("super", '__self__'): ('r', G_TYPE),
            ("super", '__self_class__'): ('r', G_TYPE),
            ("SystemExit", 'message'): ('rwd', G_STR),
            ("SystemExit", 'code'): ('rwd', G_OBJECT),
            ("type", '__basicsize__'): ('r', G_INT),
            ("type", '__itemsize__'): ('r', G_INT),
            ("type", '__base__'): ('r', G_TYPE),
            ("type", '__flags__'): ('r', G_INT),
            ("type", '__mro__'): ('r', G_TUPLE),
            ("type", '__bases__'): ('r', G_TUPLE),
            ("type", '__dictoffset__'): ('r', G_INT),
            ("type", '__dict__'): ('r', G_DICT),
            ("type", '__name__'): ('r', G_STR),
            ("type", '__weakrefoffset__'): ('r', G_INT),
            ("UnicodeDecodeError", '__basicsize__'): None,
            ("UnicodeDecodeError", '__itemsize__'): None,
            ("UnicodeDecodeError", '__base__'): None,
            ("UnicodeDecodeError", '__flags__'): ('rwd', G_INT),
            ("UnicodeDecodeError", '__mro__'): None,
            ("UnicodeDecodeError", '__bases__'): None,
            ("UnicodeDecodeError", '__dictoffset__'): None,
            ("UnicodeDecodeError", '__dict__'): None,
            ("UnicodeDecodeError", '__name__'): None,
            ("UnicodeDecodeError", '__weakrefoffset__'): None,
            ("UnicodeEncodeError", 'end'): ('rwd', G_INT),
            ("UnicodeEncodeError", 'encoding'): ('rwd', G_STR),
            ("UnicodeEncodeError", 'object'): ('rwd', G_OBJECT),
            ("UnicodeEncodeError", 'start'): ('rwd', G_INT),
            ("UnicodeEncodeError", 'reason'): ('rwd', G_STR),
            ("UnicodeEncodeError", 'message'): ('rwd', G_STR),
            ("UnicodeTranslateError", 'end'): ('rwd', G_INT),
            ("UnicodeTranslateError", 'encoding'): ('rwd', G_STR),
            ("UnicodeTranslateError", 'object'): ('rwd', G_OBJECT),
            ("UnicodeTranslateError", 'start'): ('rwd', G_INT),
            ("UnicodeTranslateError", 'reason'): ('rwd', G_STR),
            ("UnicodeTranslateError", 'message'): ('rwd', G_STR),
        },
        '_ast': {
            ("AST", '__dict__'): ('rd', G_DICT),
        },
        'posix': {
            ("statvfs_result", 'f_flag'): ('r', G_INT),
            ("statvfs_result", 'f_bavail'): ('r', G_INT),
            ("statvfs_result", 'f_favail'): ('r', G_INT),
            ("statvfs_result", 'f_files'): ('r', G_INT),
            ("statvfs_result", 'f_frsize'): ('r', G_INT),
            ("statvfs_result", 'f_blocks'): ('r', G_INT),
            ("statvfs_result", 'f_ffree'): ('r', G_INT),
            ("statvfs_result", 'f_bfree'): ('r', G_INT),
            ("statvfs_result", 'f_namemax'): ('r', G_INT),
            ("statvfs_result", 'f_bsize'): ('r', G_INT),

            ("stat_result", 'st_ctime'): ('r', G_INT),
            ("stat_result", 'st_rdev'): ('r', G_INT),
            ("stat_result", 'st_mtime'): ('r', G_INT),
            ("stat_result", 'st_blocks'): ('r', G_INT),
            ("stat_result", 'st_gid'): ('r', G_INT),
            ("stat_result", 'st_nlink'): ('r', G_INT),
            ("stat_result", 'st_ino'): ('r', G_INT),
            ("stat_result", 'st_blksize'): ('r', G_INT),
            ("stat_result", 'st_dev'): ('r', G_INT),
            ("stat_result", 'st_size'): ('r', G_INT),
            ("stat_result", 'st_mode'): ('r', G_INT),
            ("stat_result", 'st_uid'): ('r', G_INT),
            ("stat_result", 'st_atime'): ('r', G_INT),
        },
        "pwd": {
            ("struct_pwent", 'pw_dir'): ('r', G_STR),
            ("struct_pwent", 'pw_gid'): ('r', G_INT),
            ("struct_pwent", 'pw_passwd'): ('r', G_STR),
            ("struct_pwent", 'pw_gecos'): ('r', G_STR),
            ("struct_pwent", 'pw_shell'): ('r', G_STR),
            ("struct_pwent", 'pw_name'): ('r', G_STR),
            ("struct_pwent", 'pw_uid'): ('r', G_INT),

            ("struct_passwd", 'pw_dir'): ('r', G_STR),
            ("struct_passwd", 'pw_gid'): ('r', G_INT),
            ("struct_passwd", 'pw_passwd'): ('r', G_STR),
            ("struct_passwd", 'pw_gecos'): ('r', G_STR),
            ("struct_passwd", 'pw_shell'): ('r', G_STR),
            ("struct_passwd", 'pw_name'): ('r', G_STR),
            ("struct_passwd", 'pw_uid'): ('r', G_INT),
        },
        "thread": {
            ("_local", '__dict__'): None
        },
        "xxsubtype": {
            ("spamdict", 'state'): ('r', G_INT),
            ("spamlist", 'state'): ('r', G_INT),
        },
        "zipimport": {
            ("zipimporter", 'prefix'): ('r', G_STR),
            ("zipimporter", 'archive'): ('r', G_STR),
            ("zipimporter", '_files'): ('r', G_DICT),
        },
        "datetime": {
            ("datetime", "hour"): ('r', G_INT),
            ("datetime", "minute"): ('r', G_INT),
            ("datetime", "second"): ('r', G_INT),
            ("datetime", "microsecond"): ('r', G_INT),
        },
    }

    # modules that seem to re-export names but surely don't
    # ("qualified_module_name",..)
    KNOWN_FAKE_REEXPORTERS = (
      "gtk._gtk",
      "gobject._gobject",
      "numpy.core.multiarray",
      "numpy.core._dotblas",
      "numpy.core.umath",
    )

    # Some builtin classes effectively change __init__ signature without overriding it.
    # This callable serves as a placeholder to be replaced via REDEFINED_BUILTIN_SIGS
    def fake_builtin_init(self): pass # just a callable, sig doesn't matter

    fake_builtin_init.__doc__ = object.__init__.__doc__ # this forces class's doc to be used instead

    # This is a list of builtin classes to use fake init
    FAKE_BUILTIN_INITS = (tuple, type, int, str)
    if version[0] < 3:
        import __builtin__ as b2

        FAKE_BUILTIN_INITS = FAKE_BUILTIN_INITS + (getattr(b2, "unicode"),)
        del b2
    else:
        import builtins as b2

        FAKE_BUILTIN_INITS = FAKE_BUILTIN_INITS + (getattr(b2, "str"), getattr(b2, "bytes"))
        del b2

    # Some builtin methods are decorated, but this is hard to detect.
    # {("class_name", "method_name"): "decorator"}
    KNOWN_DECORATORS = {
        ("dict", "fromkeys"): "staticmethod",
        ("object", "__subclasshook__"): "classmethod",
    }

    def isSkippedInModule(self, p_module, p_value):
        "Returns True if p_value's value must be skipped for module p_module."
        skip_list = self.SKIP_VALUE_IN_MODULE.get(p_module, [])
        if p_value in skip_list:
            return True
        skip_list = self.SKIP_VALUE_IN_MODULE.get("*", [])
        if p_value in skip_list:
            return True
        return False


    def findImportedName(self, item):
        """
        Finds out how the item is represented in imported modules.
        @param item what to check
        @return qualified name (like "sys.stdin") or None
        """
        if not isinstance(item, SIMPLEST_TYPES):
            for mname in self.imported_modules:
                m = self.imported_modules[mname]
                for inner_name in m.__dict__:
                    suspect = getattr(m, inner_name)
                    if suspect is item:
                        if mname:
                            mname += "."
                        elif self.module is the_builtins: # don't short-circuit builtins
                            return None
                        return mname + inner_name
        return None

    _initializers = ( # what if types are not hashable in some strange implementation?
      (dict, "{}"),
      (tuple, "()"),
      (list, "[]"),
    )
    def inventInitializer(self, a_type):
      """
      Returns an innocuous initializer expression for a_type, or "None"
      """
      for t, r in self._initializers:
          if t == a_type:
              return r
      # NOTE: here we could handle things like defaultdict, sets, etc if we wanted
      return "None"


    def fmtValue(self, p_value, indent, prefix="", postfix="", as_name=None, seen_values=None):
        """
        Formats and outputs value (it occupies and entire line).
        @param p_value the value.
        @param indent indent level.
        @param prefix text to print before the value
        @param postfix text to print after the value
        @param as_name hints which name are we trying to print; helps with circular refs.
        @param seen_values a list of keys we've seen if we're processing a dict
        """
        SELF_VALUE = "<value is a self-reference, replaced by this string>"
        if isinstance(p_value, SIMPLEST_TYPES):
            self.out(prefix + reliable_repr(p_value) + postfix, indent)
        else:
            if sys.platform == "cli":
                imported_name = None
            else:
                imported_name = self.findImportedName(p_value)
            if imported_name:
                self.out(prefix + imported_name + postfix, indent)
            else:
                if isinstance(p_value, (list, tuple)):
                    if not seen_values:
                        seen_values = [p_value]
                    if len(p_value) == 0:
                        self.out(prefix + repr(p_value) + postfix, indent)
                    else:
                        if isinstance(p_value, list):
                            lpar, rpar = "[", "]"
                        else:
                            lpar, rpar = "(", ")"
                        self.out(prefix + lpar, indent)
                        for v in p_value:
                            if v in seen_values:
                                v = SELF_VALUE
                            elif not isinstance(v, SIMPLEST_TYPES):
                                seen_values.append(v)
                            self.fmtValue(v, indent + 1, postfix=",", seen_values=seen_values)
                        self.out(rpar + postfix, indent)
                elif isinstance(p_value, dict):
                    if len(p_value) == 0:
                        self.out(prefix + repr(p_value) + postfix, indent)
                    else:
                        if not seen_values:
                          seen_values = [p_value]
                        self.out(prefix + "{", indent)
                        for k in p_value:
                            v = p_value[k]
                            if v in seen_values:
                                v = SELF_VALUE
                            elif not isinstance(v, SIMPLEST_TYPES):
                                seen_values.append(v)
                            if isinstance(k, SIMPLEST_TYPES):
                                self.fmtValue(v, indent + 1, prefix=repr(k) + ": ", postfix=",", seen_values=seen_values)
                            else:
                            # both key and value need fancy formatting
                                self.fmtValue(k, indent + 1, postfix=": ", seen_values=seen_values)
                                self.fmtValue(v, indent + 2, seen_values=seen_values)
                                self.out(",", indent + 1)
                        self.out("}" + postfix, indent)
                else: # something else, maybe representable
                    # look up this value in the module.
                    if sys.platform == "cli":
                        self.out(prefix + "None" + postfix, indent)
                        return
                    found_name = ""
                    for inner_name in self.module.__dict__:
                        if self.module.__dict__[inner_name] is p_value:
                            found_name = inner_name
                            break
                    if self._defined.get(found_name, False):
                        self.out(prefix + found_name + postfix, indent)
                    else:
                    # a forward / circular declaration happens
                        notice = ""
                        s = cleanup(repr(p_value))
                        if found_name:
                            if found_name == as_name:
                                notice = " # (!) real value is " + s
                                s = "None"
                            else:
                                notice = " # (!) forward: " + found_name + ", real value is " + s
                        if SANE_REPR_RE.match(s):
                            self.out(prefix + s + postfix + notice, indent)
                        else:
                            if not found_name:
                                notice = " # (!) real value is " + s
                            self.out(prefix + "None" + postfix + notice, indent)


    def seemsToHaveSelf(self, reqargs):
        """"
        @param requargs a list of required arguments of a method
        @return true if param_name looks like a 'self' parameter
        """
        return reqargs and reqargs[0] == "self"

    def getRetType(self, s):
        """
        Returns a return type string as given by T_RETURN in tokens, or None
        """
        if s:
            v = RET_TYPE.get(s, None)
            if v:
                return v
            thing = getattr(self.module, s, None)
            if thing:
                return s
        # TODO: handle things like "[a, b,..] and (foo,..)"
        return None

    SIG_DOC_NOTE = "restored from __doc__"
    SIG_DOC_UNRELIABLY = "NOTE: unreliably restored from __doc__ "

    def restoreByDocString(self, signature_string, class_name, deco=None, ret_hint=None):
        """
        @param signature_string: parameter list extracted from the doc string.
        @param class_name: name of the containing class, or None
        @param deco: decorator to use
        @param ret_hint: return type hint, if available
        @return (reconstructed_spec, return_type, note) or (None, _, _) if failed.
        """
        # parse
        parsing_failed = False
        ret_type = None
        try:
            # strict parsing
            tokens = paramSeqAndRest.parseString(signature_string, True)
            ret_name = None
            if tokens:
              ret_t = tokens[-1]
              if ret_t[0] is T_RETURN:
                ret_name = ret_t[1]
            ret_type = self.getRetType(ret_name) or self.getRetType(ret_hint)
        except ParseException:
            # it did not parse completely; scavenge what we can
            parsing_failed = True
            tokens = []
            try:
                # most unrestrictive parsing
                tokens = paramSeq.parseString(signature_string, False)
            except ParseException:
                pass
            #
        seq = transformSeq(tokens)

        # add safe defaults for unparsed
        if parsing_failed:
            note = self.SIG_DOC_UNRELIABLY
            starred = None
            double_starred = None
            for one in seq:
                if type(one) is str:
                    if one.startswith("**"):
                        double_starred = one
                    elif one.startswith("*"):
                        starred = one
            if not starred:
                seq.append("*args")
            if not double_starred:
                seq.append("**kwargs")
        else:
            note = self.SIG_DOC_NOTE

        # add 'self' if needed YYY
        if class_name:
            first_param = self.proposeFirstParam(deco)
            if first_param:
                seq.insert(0, first_param)
        seq = makeNamesUnique(seq)
        return (seq, ret_type, note)

    def parseFuncDoc(self, func_doc, func_id, func_name, class_name, deco=None, sip_generated=False):
        """
        @param func_doc: __doc__ of the function.
        @param func_id: name to look for as identifier of the function in docstring
        @param func_name: name of the function.
        @param class_name: name of the containing class, or None
        @param deco: decorator to use
        @return (reconstructed_spec, return_literal, note) or (None, _, _) if failed.
        """
        if sip_generated:
            overloads = []
            for l in func_doc.split('\n'):
                signature = func_id + '('
                i = l.find(signature)
                if i >= 0:
                    overloads.append(l[i+len(signature):])
            if len(overloads) > 1:
                param_lists = [self.restoreByDocString(s, class_name, deco)[0] for s in overloads]
                ret_types = []
                for pl in param_lists:
                    rt = pl[1]
                    if rt and rt not in ret_types:
                        ret_types.append(rt)
                if ret_types:
                    ret_literal = " or ".join(ret_types)
                else:
                    ret_literal = None
                spec = self.buildSignature(func_name, self.restoreParametersForOverloads(param_lists))
                return (spec, ret_literal, "restored from __doc__ with multiple overloads")

        # find the first thing to look like a definition
        prefix_re = re.compile("\s*(?:(\w+)[ \\t]+)?" + func_id + "\s*\(") # "foo(..." or "int foo(..."
        match = prefix_re.search(func_doc)
        # parse the part that looks right
        if match:
            ret_hint = match.group(1)
            params, ret_literal, note = self.restoreByDocString(func_doc[match.end():], class_name, deco, ret_hint)
            spec = func_name + flatten(params)
            # if "NOTE" in note:
            # print "------\n", func_name, "@", match.end()
            # print "------\n", func_doc
            # print
            return (spec, ret_literal, note)
        else:
            return (None, None, None)

    def isPredefinedBuiltin(self, module_name, class_name, func_name):
        return self.doing_builtins and module_name == BUILTIN_MOD_NAME and (class_name, func_name) in self.PREDEFINED_BUILTIN_SIGS

    def restorePredefinedBuiltin(self, class_name, func_name):
        spec = func_name + self.PREDEFINED_BUILTIN_SIGS[(class_name, func_name)]
        note = "known special case of " + (class_name and class_name + "." or "") + func_name
        return (spec, note)

    def restoreByInspect(self, p_func):
        "Returns paramlist restored by inspect."
        args, varg, kwarg, defaults = inspect.getargspec(p_func)
        spec = []
        if defaults:
            dcnt = len(defaults) - 1
        else:
            dcnt = -1
        args = args or []
        args.reverse() # backwards, for easier defaults handling
        for arg in args:
            if dcnt >= 0:
                arg += "=" + sanitizeValue(defaults[dcnt])
                dcnt -= 1
            spec.insert(0, arg)
        if varg:
            spec.append("*" + varg)
        if kwarg:
            spec.append("**" + kwarg)
        return flatten(spec)

    def restoreParametersForOverloads(self, parameter_lists):
        param_index = 0
        star_args = False
        optional = False
        params = []
        while True:
            parameter_lists_copy = [pl for pl in parameter_lists]
            for pl in parameter_lists_copy:
                if param_index >= len(pl):
                    parameter_lists.remove(pl)
                    optional = True
            if not parameter_lists:
                break
            name = parameter_lists[0][param_index]
            for pl in parameter_lists[1:]:
                if pl[param_index] != name:
                    star_args = True
                    break
            if star_args: break
            if optional and not '=' in name:
                params.append(name + '=None')
            else:
                params.append(name)
            param_index += 1
        if star_args:
            params.append("*__args")
        return params

    def buildSignature(self, p_name, params):
        return p_name + '(' + ', '.join(params) + ')'

    def restoreClr(self, p_name, p_class):
        """Restore the function signature by the CLR type signature"""
        clr_type = clr.GetClrType(p_class)
        if p_name == '__new__':
            methods = [c for c in clr_type.GetConstructors()]
            if not methods:
                return p_name + '(*args)', 'cannot find CLR constructor'
        else:
            methods = [m for m in clr_type.GetMethods() if m.Name == p_name]
            if not methods:
                bases = p_class.__bases__
                if len(bases) == 1 and p_name in dir(bases[0]):
                # skip inherited methods
                    return None, None
                return p_name + '(*args)', 'cannot find CLR method'

        parameter_lists = []
        for m in methods:
            parameter_lists.append([p.Name for p in m.GetParameters()])
        params = self.restoreParametersForOverloads(parameter_lists)
        if not methods[0].IsStatic:
            params = ['self'] + params
        return self.buildSignature(p_name, params), None

    def redoFunction(self, p_func, p_name, indent, p_class=None, p_modname=None):
        """
        Restore function argument list as best we can.
        @param p_func function or method object
        @param p_name function name as known to owner
        @param indent indentation level
        @param p_class the class that contains this function as a method
        """

        # real work
        classname = p_class and p_class.__name__ or None
        if p_class and hasattr(p_class, '__mro__'):
            sip_generated = [t for t in p_class.__mro__ if 'sip.simplewrapper' in str(t)]
        else:
            sip_generated = False
        deco = None
        deco_comment = ""
        mod_class_method_tuple = (p_modname, classname, p_name)
        ret_literal = None
        # any decorators?
        if self.doing_builtins and p_modname == BUILTIN_MOD_NAME:
            deco = self.KNOWN_DECORATORS.get((classname, p_name), None)
            if deco:
                deco_comment = " # known case"
        elif p_class and p_name in p_class.__dict__:
            # detect native methods declared with METH_CLASS flag
            descriptor = p_class.__dict__[p_name]
            if p_name != "__new__" and type(descriptor).__name__.startswith('classmethod' ):
                # 'classmethod_descriptor' in Python 2.x and 3.x, 'classmethod' in Jython
                deco = "classmethod"
            elif type(p_func).__name__.startswith('staticmethod'):
                deco = "staticmethod"
        if p_name == "__new__":
            deco = "staticmethod"
            deco_comment = " # known case of __new__"

        if deco and HAS_DECORATORS:
            self.out("@" + deco + deco_comment, indent)
        if inspect and inspect.isfunction(p_func):
            self.out("def " + p_name + self.restoreByInspect(p_func) + ": # reliably restored by inspect", indent)
            self.outDocAttr(p_func, indent + 1, p_class)
        elif self.isPredefinedBuiltin(*mod_class_method_tuple):
            spec, sig_note = self.restorePredefinedBuiltin(classname, p_name)
            self.out("def " + spec + ": # " + sig_note, indent)
            self.outDocAttr(p_func, indent + 1, p_class)
        elif sys.platform == 'cli' and is_clr_type(p_class):
            spec, sig_note = self.restoreClr(p_name, p_class)
            if not spec: return
            if sig_note:
                self.out("def " + spec + ": #" + sig_note, indent)
            else:
                self.out("def " + spec + ":", indent)
            if not p_name in ['__gt__', '__ge__', '__lt__', '__le__', '__ne__', '__reduce_ex__', '__str__']:
                self.outDocAttr(p_func, indent + 1, p_class)
        elif mod_class_method_tuple in self.PREDEFINED_MOD_CLASS_SIGS:
            sig, ret_literal = self.PREDEFINED_MOD_CLASS_SIGS[mod_class_method_tuple]
            if classname:
                ofwhat = "%s.%s.%s" % mod_class_method_tuple
            else:
                ofwhat = "%s.%s" % (p_modname, p_name)
            self.out("def " + p_name + sig + (": # known case of %s" % ofwhat), indent)
            self.outDocAttr(p_func, indent + 1, p_class)
        else:
        # __doc__ is our best source of arglist
            sig_note = "real signature unknown"
            spec = ""
            is_init = (p_name == "__init__" and p_class is not None)
            funcdoc = None
            if is_init and hasattr(p_class, "__doc__"):
                if hasattr(p_func, "__doc__"):
                    funcdoc = p_func.__doc__
                if funcdoc == object.__init__.__doc__:
                    funcdoc = p_class.__doc__
            elif hasattr(p_func, "__doc__"):
                funcdoc = p_func.__doc__
            sig_restored = False
            if isinstance(funcdoc, STR_TYPES):
                (spec, ret_literal, more_notes) = self.parseFuncDoc(funcdoc, p_name, p_name, classname, deco, sip_generated)
                if spec is None and p_name == '__init__' and classname:
                    (spec, ret_literal, more_notes) = self.parseFuncDoc(funcdoc, classname, p_name, classname, deco, sip_generated)
                sig_restored = spec is not None
                if more_notes:
                    if sig_note:
                        sig_note += "; "
                    sig_note += more_notes
            if not sig_restored:
            # use an allow-all declaration
                decl = []
                if p_class:
                    first_param = self.proposeFirstParam(deco)
                    if first_param:
                        decl.append(first_param)
                decl.append("*args")
                decl.append("**kwargs")
                spec = p_name + "(" + ", ".join(decl) + ")"
            self.out("def " + spec + ": # " + sig_note, indent)
            # to reduce size of stubs, don't output same docstring twice for class and its __init__ method
            if not is_init or funcdoc != p_class.__doc__:
                self.outDocstring(funcdoc, indent + 1)
        # body
        if ret_literal:
          self.out("return " + ret_literal, indent + 1)
        else:
          self.out("pass", indent + 1)
        if deco and not HAS_DECORATORS:
            self.out(p_name + " = " + deco + "(" + p_name + ")" + deco_comment, indent)
        self.out("", 0) # empty line after each item

    def proposeFirstParam(self, deco):
        "@return: name of missing first paramater, considering a decorator"
        if deco is None:
            return "self"
        if deco == "classmethod":
            return "cls"
        # if deco == "staticmethod":
        return None

    def fullName(self, cls, p_modname):
        m = cls.__module__
        if m == p_modname or m == BUILTIN_MOD_NAME or m == 'exceptions':
            return cls.__name__
        return m + "." + cls.__name__

    def redoClass(self, p_class, p_name, indent, p_modname=None):
        """
        Restores a class definition.
        @param p_class the class object
        @param p_name function name as known to owner
        @param indent indentation level
        """
        bases = getBases(p_class)
        base_def = ""
        if bases:
            base_def = "(" + ", ".join([self.fullName(x, p_modname) for x in bases]) + ")"
        self.out("class " + p_name + base_def + ":", indent)
        self.outDocAttr(p_class, indent + 1)
        # inner parts
        methods = {}
        properties = {}
        others = {}
        if hasattr(p_class, "__dict__"):
            we_are_the_base_class = p_modname == BUILTIN_MOD_NAME and p_name in ("object", FAKE_CLASSOBJ_NAME)
            for item_name in p_class.__dict__:
                if item_name in ("__doc__", "__module__"):
                    if we_are_the_base_class:
                        item = "" # must be declared in base types
                    else:
                        continue # in all other cases. must be skipped
                elif keyword.iskeyword(item_name):    # for example, PyQt4 contains definitions of methods named 'exec'
                    continue
                else:
                    try:
                        item = getattr(p_class, item_name) # let getters do the magic
                    except:
                        item = p_class.__dict__[item_name]   # have it raw
                if isCallable(item):
                    methods[item_name] = item
                elif isProperty(item):
                    properties[item_name] = item
                else:
                    others[item_name] = item
                #
            if we_are_the_base_class:
                others["__dict__"] = {} # force-feed it, for __dict__ does not contain a reference to itself :)
            # add fake __init__s to type and tuple to have the right sig
            if p_class in self.FAKE_BUILTIN_INITS:
                methods["__init__"] = self.fake_builtin_init
            elif '__init__' not in methods:
                init_method = getattr(p_class, '__init__')
                if init_method: methods['__init__'] = init_method
                
            #
            for item_name in sortedNoCase(methods.keys()):
                item = methods[item_name]
                self.redoFunction(item, item_name, indent + 1, p_class, p_modname)
            #
            known_props = self.KNOWN_PROPS.get(p_modname, {})
            a_setter = "lambda self, v: None"
            a_deleter = "lambda self: None"
            for item_name in sortedNoCase(properties.keys()):
                prop_key = (p_name, item_name)
                if prop_key in known_props:
                    prop_descr = known_props.get(prop_key, None)
                    if prop_descr is None:
                        continue # explicitly omitted
                    acc_line, getter = prop_descr
                    accessors = []
                    accessors.append("r" in acc_line and getter or "None")
                    accessors.append("w" in acc_line and a_setter or "None")
                    accessors.append("d" in acc_line and a_deleter or "None")
                    self.out(item_name + " = property(" + ", ".join(accessors) + ")", indent + 1)
                else:
                    self.out(item_name + " = property(lambda self: object(), None, None) # default", indent + 1)
                # TODO: handle docstring
            if properties:
                self.out("", 0) # empty line after the block
            #
            for item_name in sortedNoCase(others.keys()):
                item = others[item_name]
                self.fmtValue(item, indent + 1, prefix=item_name + " = ")
            if others:
                self.out("", 0) # empty line after the block
            #
        if not methods and not properties and not others:
            self.out("pass", indent + 1)

    def redo(self, p_name, imported_module_names):
        """
        Restores module declarations.
        Intended for built-in modules and thus does not handle import statements.
        """
        self.out("# encoding: utf-8", 0) # NOTE: maybe encoding should be selectable
        if hasattr(self.module, "__name__"):
            self_name = self.module.__name__
            if self_name != p_name:
              mod_name = " calls itself " + self_name
            else:
              mod_name = ""
        else:
            mod_name = " does not know its name"
        if p_name == BUILTIN_MOD_NAME and version[0] == 2 and version[1] >= 6:
            self.out("from __future__ import print_function", 0)
        self.out("# module " + p_name + mod_name, 0)
        if hasattr(self.module, "__file__"):
            self.out("# from file " + self.module.__file__, 0)
        self.outDocAttr(self.module, 0)
        # find whatever other self.imported_modules the module knows; effectively these are imports
        module_type = type(sys)
        for item_name, item in self.module.__dict__.items():
            if isinstance(item, module_type):
                self.imported_modules[item_name] = item
                if hasattr(item, "__name__"):
                    self.out("import " + item.__name__ + " as " + item_name + " # refers to " + str(item))
                else:
                    self.out(item_name + " = None # ??? name unknown, refers to " + str(item))
        for module_name, module_obj in sys.modules.items():
            if module_name in imported_module_names and module_obj != self.module and module_name not in self.imported_modules and module_obj:
                self.imported_modules[module_name] = module_obj
                self.out("import " + module_name)
                                
        self.out("", 0) # empty line after imports
        # group what else we have into buckets
        vars_simple = {}
        vars_complex = {}
        funcs = {}
        classes = {}
        reexports = {} # contains not real objects, but qualified id strings, like "sys.stdout"
        #
        for item_name in self.module.__dict__:
            if item_name in ("__dict__", "__doc__", "__module__", "__file__", "__name__", "__builtins__", "__package__"):
                continue
            try:
                item = getattr(self.module, item_name) # let getters do the magic
            except:
                item = self.module.__dict__[item_name] # have it raw
            # check if it has percolated from an imported module
            if sys.platform == "cli" and p_name != "System":
                # IronPython has non-trivial reexports in System module, but not in others
                imported_name = None
            elif p_name in self.KNOWN_FAKE_REEXPORTERS:
                # some weirdness with module references, can't figure it out, assume no reexports
                imported_name = None
            else:
                imported_name = self.findImportedName(item)
            if imported_name is not None:
                reexports[item_name] = imported_name
            else:
                if isinstance(item, type) or item is FakeClassObj: # some classes are callable, check them before functions
                    classes[item_name] = item
                elif isCallable(item):
                    funcs[item_name] = item
                elif isinstance(item, module_type):
                    continue # self.imported_modules handled above already
                else:
                    if isinstance(item, SIMPLEST_TYPES):
                        vars_simple[item_name] = item
                    else:
                        vars_complex[item_name] = item
                    #
                    # sort and output every bucket
        if reexports:
            self.out("# reexported imports", 0)
            self.out("", 0)
            for item_name in sortedNoCase(reexports.keys()):
                item = reexports[item_name]
                self.out(item_name + " = " + item, 0)
                self._defined[item_name] = True
            self.out("", 0) # empty line after group
        #
        omitted_names = self.OMIT_NAME_IN_MODULE.get(p_name, [])
        if vars_simple:
            prefix = "" # try to group variables by common prefix
            PREFIX_LEN = 2 # default prefix length if we can't guess better
            self.out("# Variables with simple values", 0)
            for item_name in sortedNoCase(vars_simple.keys()):
                if item_name in omitted_names:
                  self.out("# definition of " + item_name + " omitted", 0)
                  continue
                item = vars_simple[item_name]
                # track the prefix
                if len(item_name) >= PREFIX_LEN:
                    prefix_pos = string.rfind(item_name, "_") # most prefixes end in an underscore
                    if prefix_pos < 1:
                        prefix_pos = PREFIX_LEN
                    beg = item_name[0:prefix_pos]
                    if prefix != beg:
                        self.out("", 0) # space out from other prefix
                        prefix = beg
                else:
                    prefix = ""
                # output
                replacement = self.REPLACE_MODULE_VALUES.get((p_name, item_name), None)
                if replacement is not None:
                    self.out(item_name + " = " + replacement + " # real value of type " + str(type(item)) + " replaced", 0)
                elif self.isSkippedInModule(p_name, item_name):
                    t_item = type(item)
                    self.out(item_name + " = " + self.inventInitializer(t_item) +  " # real value of type " + str(t_item) + " skipped", 0)
                else:
                    self.fmtValue(item, 0, prefix=item_name + " = ")
                self._defined[item_name] = True
            self.out("", 0) # empty line after vars
        #
        if funcs:
            self.out("# functions", 0)
            self.out("", 0)
            for item_name in sortedNoCase(funcs.keys()):
                if item_name in omitted_names:
                  self.out("# definition of " + item_name + " omitted", 0)
                  continue
                item = funcs[item_name]
                self.redoFunction(item, item_name, 0, p_modname=p_name)
                self._defined[item_name] = True
                self.out("", 0) # empty line after each item
        else:
            self.out("# no functions", 0)
        #
        if classes:
            self.out("# classes", 0)
            self.out("", 0)
            # sort classes so that inheritance order is preserved
            cls_list = [] # items are (class_name, mro_tuple)
            for cls_name in sortedNoCase(classes.keys()):
                cls = classes[cls_name]
                ins_index = len(cls_list)
                for i in range(ins_index):
                    maybe_child_bases = cls_list[i][1]
                    if cls in maybe_child_bases:
                        ins_index = i # we could not go farther than current ins_index
                        break         # ...and need not go fartehr than first known child
                cls_list.insert(ins_index, (cls_name, getMRO(cls)))
            for item_name in [cls_item[0] for cls_item in cls_list]:
                if item_name in omitted_names:
                  self.out("# definition of " + item_name + " omitted", 0)
                  continue
                item = classes[item_name]
                self.redoClass(item, item_name, 0, p_modname=p_name)
                self._defined[item_name] = True
                self.out("", 0) # empty line after each item
        else:
            self.out("# no classes", 0)
        #
        if vars_complex:
            self.out("# variables with complex values", 0)
            self.out("", 0)
            for item_name in sortedNoCase(vars_complex.keys()):
                if item_name in omitted_names:
                  self.out("# definition of " + item_name + " omitted", 0)
                  continue
                item = vars_complex[item_name]
                replacement = self.REPLACE_MODULE_VALUES.get((p_name, item_name), None)
                if replacement is not None:
                    self.out(item_name + " = " + replacement + " # real value of type " + str(type(item)) + " replaced", 0)
                elif self.isSkippedInModule(p_name, item_name):
                    t_item = type(item)
                    self.out(item_name + " = " + self.inventInitializer(t_item) +  " # real value of type " + str(t_item) + " skipped", 0)
                else:
                    self.fmtValue(item, 0, prefix=item_name + " = ", as_name=item_name)
                self._defined[item_name] = True
                self.out("", 0) # empty line after each item
        values_to_add = self.ADD_VALUE_IN_MODULE.get(p_name, None)
        if values_to_add:
            self.out("# intermittent names", 0)
            for v in values_to_add:
                self.out(v, 0)


def build_output_name(subdir, name):
    quals = name.split(".")
    dirname = subdir
    if dirname:
        dirname += os.path.sep # "a -> a/"
    for pathindex in range(len(quals) - 1): # create dirs for all quals but last
        subdirname = dirname + os.path.sep.join(quals[0: pathindex + 1])
        if not os.path.isdir(subdirname):
            action = "creating subdir " + subdirname
            os.makedirs(subdirname)
        init_py = os.path.join(subdirname, "__init__.py")
        if os.path.isfile(subdirname + ".py"):
            os.rename(subdirname + ".py", init_py)
        elif not os.path.isfile(init_py):
            init = fopen(init_py, "w")
            init.close()
    target_dir = dirname + os.path.sep.join(quals[0: len(quals) - 1])
    #sys.stderr.write("target dir is " + repr(target_dir) + "\n")
    target_name = target_dir + os.path.sep + quals[-1]
    if os.path.isdir(target_name):
        fname = os.path.join(target_name, "__init__.py")
    else:
        fname = target_name + ".py"
    return fname

action = None
def redo_module(name, fname, imported_module_names):
    global action
    # gobject does 'del _gobject' in its __init__.py, so the chained attribute lookup code
    # fails to find 'gobject._gobject'. thus we need to pull the module directly out of
    # sys.modules
    mod = sys.modules[name]
    if not mod:
        sys.stderr.write("Failed to find imported module in sys.modules")
        #sys.exit(0)

    if update_mode and hasattr(mod, "__file__"):
        action = "probing " + fname
        mod_mtime = os.path.exists(mod.__file__) and os.path.getmtime(mod.__file__) or 0.0
        file_mtime = os.path.exists(fname) and os.path.getmtime(fname) or 0.0
        # skeleton's file is no older than module's, and younger than our script
        if file_mtime >= mod_mtime and datetime.fromtimestamp(file_mtime) > OUR_OWN_DATETIME:
            return # skip the file

    if doing_builtins and name == BUILTIN_MOD_NAME:
        action = "grafting"
        setattr(mod, FAKE_CLASSOBJ_NAME, FakeClassObj)
    action = "opening " + fname
    outfile = fopen(fname, "w")
    action = "restoring"
    r = ModuleRedeclarator(mod, outfile, doing_builtins=doing_builtins)
    r.redo(name, imported_module_names)
    action = "closing " + fname
    outfile.close()


# command-line interface

if __name__ == "__main__":
    from getopt import getopt
    import os

    if sys.version_info[0] > 2:
        import io  # in 3.0

        fopen = lambda name, mode: io.open(name, mode, encoding='utf-8')
    else:
        fopen = open

    # handle cmdline
    helptext = """Generates interface skeletons for python modules.
  Usage: generator [options] [name ...]
  Every "name" is a (qualified) module name, e.g. "foo.bar"
  Output files will be named as modules plus ".py" suffix.
  Normally every name processed will be printed and stdout flushed. 
  Options are:
  -h -- prints this help message.
  -d dir -- output dir, must be writable. If not given, current dir is used. 
  -b -- use names from sys.builtin_module_names
  -q -- quiet, do not print anything on stdout. Errors still go to stderr.
  -u -- update, only recreate skeletons for newer files, and skip unchanged.
  -x -- die on exceptions with a stacktrace; only for debugging.
  -c modules -- import CLR assemblies with specified names
  -p -- run CLR profiler
  """
    opts, fnames = getopt(sys.argv[1:], "d:hbquxc:p")
    opts = dict(opts)
    if not opts or '-h' in opts:
        print(helptext)
        sys.exit(0)
    if '-b' not in opts and not fnames:
        sys.stderr.write("Neither -b nor any module name given\n")
        sys.exit(1)
    quiet = '-q' in opts
    update_mode = "-u" in opts
    debug_mode = "-x" in opts
    subdir = opts.get('-d', '')
    # determine names
    names = fnames
    if '-b' in opts:
        doing_builtins = True
        names.extend(sys.builtin_module_names)
        if not BUILTIN_MOD_NAME in names:
            names.append(BUILTIN_MOD_NAME)
        if '__main__' in names:
            names.remove('__main__') # we don't want ourselves processed
    else:
        doing_builtins = False

    if sys.platform == 'cli':
        refs = opts.get('-c', '')
        if refs:
            for ref in refs.split(';'): clr.AddReferenceByPartialName(ref)

        if '-p' in opts:
            atexit.register(print_profile)

        from System import DateTime

        start = DateTime.Now

    # go on
    for name in names:
        if name.endswith(".py"):
          sys.stderr.write("Ignored a regular Python file " + name + "\n")
          continue
        if not quiet:
            sys.stdout.write(name + "\n")
            sys.stdout.flush()
        action = "doing nothing"
        try:
            fname = build_output_name(subdir, name)

            old_modules = list(sys.modules.keys())
            imported_module_names = []
            class MyFinder:
                def find_module(self, fullname, path=None):
                    if fullname != name:
                        imported_module_names.append(fullname)
                    return None

            my_finder = None
            if hasattr(sys, 'meta_path'):
                my_finder = MyFinder()
                sys.meta_path.append(my_finder)
            else:
                imported_module_names = None

            action = "importing"
            try:
                mod = __import__(name)
            except ImportError:
                sys.stderr.write("Name " + name + " failed to import\n")
                continue

            if my_finder:
                sys.meta_path.remove(my_finder)
            if imported_module_names is None:
                imported_module_names = [m for m in sys.modules.keys() if m not in old_modules]

            redo_module(name, fname, imported_module_names)
            # The C library may have called Py_InitModule() multiple times to define several modules (gtk._gtk and gtk.gdk);
            # restore all of them
            if imported_module_names:
                for m in sys.modules.keys():
                    action = "restoring submodule " + m
                    # if module has __file__ defined, it has Python source code and doesn't need a skeleton 
                    if m not in old_modules and m not in imported_module_names and m != name and not hasattr(sys.modules[m], '__file__'):
                        if not quiet:
                            sys.stdout.write(m + "\n")
                            sys.stdout.flush()
                        fname = build_output_name(subdir, m)
                        redo_module(m, fname, imported_module_names)
        except:
            sys.stderr.write("Failed to process " + name + " while " + action + "\n")
            if debug_mode:
                raise
            else:
                continue

    if sys.platform == 'cli':
        print("Generation completed in " + str((DateTime.Now - start).TotalMilliseconds) + " ms")
