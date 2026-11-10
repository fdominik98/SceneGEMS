import type { SyntaxNode, Tree } from "@lezer/common";
import { parser } from "../../language/refineryProblem/problem.grammar";

/**
 * What a Refinery `.problem` text declares, read from the syntax tree of the editor's own Lezer
 * grammar (`language/refineryProblem/problem.grammar`), never from the names a specification uses.
 * One text gives both parts: the metamodel (classes, enums, predicates and the other declarations)
 * and the model (the objects and the facts asserted about them). A text with syntax errors gives what
 * the parser could read, and says how many errors it has and where the first one is.
 *
 * What the model leaves out, on purpose:
 * - `default` assertions and negative facts (`!rel(a, b).`, `rel(a, b): false.`) say what does not
 *   hold; they are counted, not drawn.
 * - `X::new` names the placeholder object of a class that stands for every further object; it is no
 *   object of the model, so an assertion that names one is counted and left out.
 * - `exists` and `equals` are Refinery's built-in relations (`!exists(OS::new).` closes a class); their
 *   assertions are counted and left out, though a plain object they name is still an object.
 * - `*` (any object) is no object; an assertion with a `*` argument is left out unless it is a default.
 * - Facts of more than two objects are counted (with their relation names), not drawn.
 * - A fact whose value is `error` is counted with the other facts that cannot be drawn.
 * An unknown fact (`?rel(a, b).`, `rel(a, b): unknown.`) is kept as a possible one.
 */

export interface ProblemSyntax {
  /** How many error nodes the parser put into the tree. */
  errorCount: number;
  /** The 1-based line of the first one, null without errors. */
  firstErrorLine: number | null;
}

export type FeatureKind = "contains" | "container" | "refers" | "plain";
/** What a feature's type names, once the whole text is read: a class (also one only used, not defined), an enum or a datatype. */
export type FeatureTarget = "class" | "enum" | "datatype";

export interface ClassFeature {
  name: string;
  /** The type as written. */
  type: string;
  /** The multiplicity between the brackets as written ("0..*", "1"), "" for `[]`, null without brackets. */
  multiplicity: string | null;
  kind: FeatureKind;
  /** The name of the opposite feature, null without `opposite`. */
  opposite: string | null;
  subsets: string[];
  target: FeatureTarget;
}

export interface MetaClass {
  name: string;
  abstract: boolean;
  superclasses: string[];
  features: ClassFeature[];
  /** False for a class the text uses (a feature's type, a superclass) without defining it. */
  defined: boolean;
  /** The 1-based line of its definition, null for one not defined. */
  line: number | null;
}

export interface MetaEnum {
  name: string;
  literals: string[];
  line: number;
}

export interface Parameter {
  name: string;
  /** The parameter's type as written, null for an untyped one. */
  type: string | null;
}

export interface MetaPredicate {
  name: string;
  parameters: Parameter[];
  /** An `error` predicate: a well-formedness constraint no model may satisfy. */
  error: boolean;
  shadow: boolean;
  partial: boolean;
  line: number;
}

export type DeclarationKind = "module" | "import" | "datatype" | "aggregator" | "primitive" | "function" | "rule" | "annotation";

/** Any other top-level declaration that belongs to a metamodel, by name. */
export interface MetaDeclaration {
  kind: DeclarationKind;
  name: string;
  line: number;
}

export interface ScopeEntry {
  relation: string;
  /** `+=` (on top of what the text declares) rather than `=`. */
  increment: boolean;
  multiplicity: string;
}

export interface Metamodel {
  /** The defined classes in their order, then the ones only used. */
  classes: MetaClass[];
  enums: MetaEnum[];
  /** The predicates in their order, error predicates among them. */
  predicates: MetaPredicate[];
  declarations: MetaDeclaration[];
  scopes: ScopeEntry[];
}

export interface NodeFact {
  relation: string;
  possible: boolean;
}

export interface NodeValue {
  relation: string;
  /** An enum literal, or the value of an attribute as written. */
  value: string;
  kind: "enum" | "attribute";
  possible: boolean;
}

export type NodeOrigin = "declare" | "multi" | "atom" | "assertion";

export interface ModelNode {
  name: string;
  /** Where the text first names it. */
  origin: NodeOrigin;
  /** The classes it is asserted to be an instance of (`Folder(root).`). */
  types: string[];
  /** The classes it may be an instance of (`?Folder(root).`). */
  possibleTypes: string[];
  /** The other true or unknown facts about it alone (`ready(job).`). */
  facts: NodeFact[];
  /** Its enum values (`state(job, Running).`) and attribute values (`size(file): 3.`). */
  values: NodeValue[];
}

export interface ModelLink {
  relation: string;
  source: string;
  target: string;
  /** An unknown fact: the link may hold. */
  possible: boolean;
  /** Asserted in both directions (`r(a, b). r(b, a).`), kept once. */
  twoWay: boolean;
}

export interface ModelOmissions {
  negative: number;
  defaults: number;
  /** Assertions about a `X::new` placeholder object. */
  newObjects: number;
  /** Assertions of `exists` and `equals`. */
  builtins: number;
  higherArity: number;
  /** Facts that cannot be drawn otherwise: an `error` value, a `*` argument outside a default, an enum literal as an object. */
  other: number;
}

export interface ProblemModel {
  /** The objects in the order the text first names them. */
  nodes: ModelNode[];
  links: ModelLink[];
  omitted: ModelOmissions;
  /** The relations of the facts of more than two objects, each once. */
  higherArityRelations: string[];
}

export interface ReadProblem {
  metamodel: Metamodel;
  model: ProblemModel;
  syntax: ProblemSyntax;
}

/** Refinery's built-in datatypes; a feature of one of these is an attribute. */
const BUILTIN_DATATYPES = new Set(["int", "real", "string", "boolean"]);
/** Refinery's built-in relations, left out of the model graph. */
const BUILTIN_RELATIONS = new Set(["exists", "equals"]);

function baseName(name: string): string {
  return name.startsWith("builtin::") ? name.slice("builtin::".length) : name;
}

/** An identifier as Refinery reads it: a quoted one without its quotes and escapes. */
function unquote(text: string): string {
  if (text.length >= 2 && text.startsWith("'") && text.endsWith("'")) {
    return text.slice(1, -1).replace(/\\(.)/gs, "$1");
  }
  return text;
}

class Reader {
  private readonly lineStarts: number[] = [0];
  private readonly text: string;

  constructor(text: string) {
    this.text = text;
    for (let index = 0; index < text.length; index++) {
      if (text.charCodeAt(index) === 10) {
        this.lineStarts.push(index + 1);
      }
    }
  }

  line(offset: number): number {
    let low = 0;
    let high = this.lineStarts.length - 1;
    while (low < high) {
      const middle = (low + high + 1) >> 1;
      if (this.lineStarts[middle] <= offset) {
        low = middle;
      } else {
        high = middle - 1;
      }
    }
    return low + 1;
  }

  source(node: SyntaxNode): string {
    return this.text.slice(node.from, node.to).replace(/\s+/g, " ").trim();
  }

  /** The name a node holds: the IDs of its qualified name joined by `::`, quotes removed; null when it holds none. */
  name(node: SyntaxNode | null): string | null {
    if (node === null) {
      return null;
    }
    const qualified = node.name === "QualifiedName" ? node : node.getChild("QualifiedName");
    if (qualified === null) {
      return null;
    }
    const parts = qualified.getChildren("ID").map((id) => unquote(this.text.slice(id.from, id.to)));
    const joined = parts.filter((part) => part.length > 0).join("::");
    return joined.length > 0 ? joined : null;
  }

  names(parent: SyntaxNode, child: string): string[] {
    return parent.getChildren(child).flatMap((node) => {
      const name = this.name(node);
      return name === null ? [] : [name];
    });
  }
}

function syntaxOf(tree: Tree, reader: Reader): ProblemSyntax {
  let errorCount = 0;
  let first: number | null = null;
  tree.iterate({
    enter: (node) => {
      if (node.type.isError) {
        errorCount += 1;
        if (first === null) {
          first = node.from;
        }
      }
    },
  });
  return { errorCount, firstErrorLine: first === null ? null : reader.line(first) };
}

function parametersOf(list: SyntaxNode | null, reader: Reader): Parameter[] {
  if (list === null) {
    return [];
  }
  return list.getChildren("Parameter").flatMap((parameter) => {
    const name = reader.name(parameter.getChild("VariableName"));
    return name === null ? [] : [{ name, type: reader.name(parameter.getChild("RelationName")) }];
  });
}

function featureOf(declaration: SyntaxNode, reader: Reader): Omit<ClassFeature, "target"> | null {
  const [typeNode, nameNode] = declaration.getChildren("RelationName");
  const type = reader.name(typeNode ?? null);
  const name = reader.name(nameNode ?? null);
  if (type === null || name === null) {
    return null;
  }
  let kind: FeatureKind = "plain";
  const head = declaration.getChild("FeatureDeclarationHeadWithKind");
  if (head !== null) {
    kind = head.getChild("contains") !== null ? "contains" : "refers";
  } else if (declaration.getChild("FeatureDeclarationHeadWithContainerKind") !== null) {
    kind = "container";
  }
  let multiplicity: string | null = null;
  if (declaration.getChild("[") !== null) {
    const written = declaration.getChild("Multiplicity");
    multiplicity = written === null ? "" : reader.source(written).replace(/\s+/g, "");
  }
  let opposite: string | null = null;
  const subsets: string[] = [];
  for (const option of declaration.getChildren("RelationOptions")) {
    const named = reader.names(option, "RelationName");
    if (option.getChild("opposite") !== null) {
      opposite = named[0] ?? opposite;
    } else {
      subsets.push(...named);
    }
  }
  return { name, type, multiplicity, kind, opposite, subsets };
}

interface RawAssertion {
  relation: string;
  /** Each argument's name, `*` for a wildcard. */
  args: string[];
  logic: "true" | "false" | "unknown" | "error";
  /** The value of an attribute as written, null for a logic value or none. */
  value: string | null;
  isDefault: boolean;
}

function assertionOf(statement: SyntaxNode, reader: Reader): RawAssertion | null {
  const relation = reader.name(statement.getChild("RelationName"));
  const list = statement.getChild("ParameterList");
  if (relation === null || list === null) {
    return null;
  }
  const args = list.getChildren("AssertionArgument").map((argument) => (argument.getChild("StarArgument") !== null ? "*" : (reader.name(argument.getChild("NodeName")) ?? "*")));
  let logic: RawAssertion["logic"] = statement.getChild("NotOp") !== null ? "false" : statement.getChild("UnknownOp") !== null ? "unknown" : "true";
  let value: string | null = null;
  const expression = statement.getChild("Expr");
  if (expression !== null && logic === "true") {
    const constant = expression.getChild("Constant")?.getChild("LogicValue") ?? null;
    const keyword = constant?.firstChild?.name;
    if (keyword === "true" || keyword === "false" || keyword === "unknown" || keyword === "error") {
      logic = keyword;
    } else {
      value = reader.source(expression);
    }
  }
  return { relation, args, logic, value, isDefault: statement.getChild("default") !== null };
}

interface Collected {
  defined: MetaClass[];
  enums: MetaEnum[];
  predicates: MetaPredicate[];
  declarations: MetaDeclaration[];
  scopes: ScopeEntry[];
  datatypes: Set<string>;
  declared: { name: string; origin: NodeOrigin }[];
  assertions: RawAssertion[];
}

type RawFeature = Omit<ClassFeature, "target">;

function collect(tree: Tree, reader: Reader): Collected & { rawFeatures: Map<MetaClass, RawFeature[]> } {
  const out: Collected & { rawFeatures: Map<MetaClass, RawFeature[]> } = {
    defined: [],
    enums: [],
    predicates: [],
    declarations: [],
    scopes: [],
    datatypes: new Set(),
    declared: [],
    assertions: [],
    rawFeatures: new Map(),
  };
  const declare = (name: string | null, kind: DeclarationKind, node: SyntaxNode) => {
    if (name !== null) {
      out.declarations.push({ kind, name, line: reader.line(node.from) });
    }
  };
  for (let statement = tree.topNode.firstChild; statement !== null; statement = statement.nextSibling) {
    const line = reader.line(statement.from);
    switch (statement.name) {
      case "ClassDefinition": {
        const [nameNode, ...supers] = statement.getChildren("RelationName");
        const name = reader.name(nameNode ?? null);
        if (name === null) {
          break;
        }
        const body = statement.getChild("ClassBody");
        const features = body === null ? [] : body.getChildren("FeatureDeclaration").flatMap((declaration) => featureOf(declaration, reader) ?? []);
        const metaClass: MetaClass = {
          name,
          abstract: statement.getChild("abstract") !== null,
          superclasses: supers.flatMap((node) => reader.name(node) ?? []),
          features: [],
          defined: true,
          line,
        };
        out.defined.push(metaClass);
        out.rawFeatures.set(metaClass, features);
        break;
      }
      case "EnumDefinition": {
        const name = reader.name(statement.getChild("RelationName"));
        if (name === null) {
          break;
        }
        const body = statement.getChild("EnumBody");
        const literals = body === null ? [] : body.getChildren("EnumLiteral").flatMap((literal) => reader.name(literal.getChild("AtomNodeName")) ?? []);
        out.enums.push({ name, literals, line });
        break;
      }
      case "PredicateDefinition": {
        const name = reader.name(statement.getChild("RelationName"));
        if (name === null) {
          break;
        }
        out.predicates.push({
          name,
          parameters: parametersOf(statement.getChild("ParameterList"), reader),
          error: statement.getChild("error") !== null,
          shadow: statement.getChild("shadow") !== null,
          partial: statement.getChild("partial") !== null,
          line,
        });
        break;
      }
      case "FunctionDefinition": {
        const [typeNode, nameNode] = statement.getChildren("RelationName");
        const type = reader.name(typeNode ?? null);
        const name = reader.name(nameNode ?? null);
        const bare = statement.getChild("ParameterList") === null && statement.getChild("FunctionBody")?.getChild("=") == null;
        // This grammar copy reads `module m.`, `atom a.` and `multi a.` (one name) as a function `module m`
        // without parameters or body, since `module`, `atom` and `multi` are contextual keywords; they are read back here.
        if (bare && type === "module") {
          declare(name, "module", statement);
        } else if (bare && (type === "multi" || type === "atom") && name !== null) {
          out.declared.push({ name, origin: type });
        } else {
          declare(name, "function", statement);
        }
        break;
      }
      case "ProblemDeclaration":
        declare(reader.name(statement.getChild("ModuleName")), "module", statement);
        break;
      case "ImportStatement":
        declare(reader.name(statement.getChild("ModuleName")), "import", statement);
        break;
      case "DatatypeDeclaration": {
        const name = reader.name(statement.getChild("DatatypeName"));
        declare(name, "datatype", statement);
        if (name !== null) {
          out.datatypes.add(name);
        }
        break;
      }
      case "AggregatorDeclaration":
        declare(reader.name(statement.getChild("AggregatorName")), "aggregator", statement);
        break;
      case "OverloadedDeclaration":
        declare(reader.name(statement.getChild("RelationName")), "primitive", statement);
        break;
      case "RuleDefinition":
        declare(reader.name(statement.getChild("RuleName")), "rule", statement);
        break;
      case "AnnotationDeclaration":
        declare(reader.name(statement.getChild("AnnotationName")), "annotation", statement);
        break;
      case "ScopeDeclaration":
        for (const element of statement.getChildren("ScopeElement")) {
          const relation = reader.name(element.getChild("RelationName"));
          const multiplicity = element.getChild("Multiplicity");
          if (relation !== null && multiplicity !== null) {
            out.scopes.push({ relation, increment: element.getChild("+=") !== null, multiplicity: reader.source(multiplicity).replace(/\s+/g, "") });
          }
        }
        break;
      case "NodeDeclaration": {
        const origin: NodeOrigin = statement.getChild("multi") !== null ? "multi" : "declare";
        for (const annotated of statement.getChildren("AnnotatedNodeName")) {
          const name = reader.name(annotated.getChild("NodeName"));
          if (name !== null) {
            out.declared.push({ name, origin });
          }
        }
        break;
      }
      case "AtomDeclaration":
        for (const literal of statement.getChildren("EnumLiteral")) {
          const name = reader.name(literal.getChild("AtomNodeName"));
          if (name !== null) {
            out.declared.push({ name, origin: "atom" });
          }
        }
        break;
      case "Assertion": {
        const assertion = assertionOf(statement, reader);
        if (assertion !== null) {
          out.assertions.push(assertion);
        }
        break;
      }
      default:
        break;
    }
  }
  return out;
}

function buildMetamodel(collected: ReturnType<typeof collect>): Metamodel {
  const enumNames = new Set(collected.enums.map((item) => item.name));
  const isDatatype = (name: string) => collected.datatypes.has(name) || BUILTIN_DATATYPES.has(baseName(name));
  const definedNames = new Set(collected.defined.map((item) => item.name));
  const used: MetaClass[] = [];
  const noteUsedClass = (name: string) => {
    if (!definedNames.has(name) && !used.some((item) => item.name === name)) {
      used.push({ name, abstract: false, superclasses: [], features: [], defined: false, line: null });
    }
  };
  for (const metaClass of collected.defined) {
    metaClass.features = (collected.rawFeatures.get(metaClass) ?? []).map((feature) => {
      const target: FeatureTarget = enumNames.has(feature.type) ? "enum" : isDatatype(feature.type) ? "datatype" : "class";
      if (target === "class") {
        noteUsedClass(feature.type);
      }
      return { ...feature, target };
    });
    for (const superclass of metaClass.superclasses) {
      if (!enumNames.has(superclass)) {
        noteUsedClass(superclass);
      }
    }
  }
  return { classes: [...collected.defined, ...used], enums: collected.enums, predicates: collected.predicates, declarations: collected.declarations, scopes: collected.scopes };
}

function buildModel(collected: ReturnType<typeof collect>, metamodel: Metamodel): ProblemModel {
  const classNames = new Set(metamodel.classes.map((item) => item.name));
  const literals = new Map<string, string>();
  for (const item of metamodel.enums) {
    for (const literal of item.literals) {
      literals.set(literal, literal);
      literals.set(`${item.name}::${literal}`, literal);
    }
  }
  const omitted: ModelOmissions = { negative: 0, defaults: 0, newObjects: 0, builtins: 0, higherArity: 0, other: 0 };
  const higherArity = new Set<string>();
  const nodes = new Map<string, ModelNode>();
  const isPlaceholder = (name: string) => name.endsWith("::new");
  const ensure = (name: string, origin: NodeOrigin) => {
    if (name === "*" || isPlaceholder(name) || literals.has(name)) {
      return;
    }
    if (!nodes.has(name)) {
      nodes.set(name, { name, origin, types: [], possibleTypes: [], facts: [], values: [] });
    }
  };
  for (const { name, origin } of collected.declared) {
    ensure(name, origin);
  }
  for (const assertion of collected.assertions) {
    for (const arg of assertion.args) {
      ensure(arg, "assertion");
    }
  }

  const links: ModelLink[] = [];
  const linkKeys = new Map<string, ModelLink>();
  for (const assertion of collected.assertions) {
    const { relation, args, logic } = assertion;
    if (assertion.isDefault) {
      omitted.defaults += 1;
      continue;
    }
    if (args.some(isPlaceholder)) {
      omitted.newObjects += 1;
      continue;
    }
    if (BUILTIN_RELATIONS.has(baseName(relation))) {
      omitted.builtins += 1;
      continue;
    }
    if (logic === "false") {
      omitted.negative += 1;
      continue;
    }
    if (args.length > 2) {
      omitted.higherArity += 1;
      higherArity.add(relation);
      continue;
    }
    const possible = logic === "unknown";
    const source = args[0] === undefined ? undefined : nodes.get(args[0]);
    if (logic === "error" || source === undefined || args.includes("*")) {
      omitted.other += 1;
      continue;
    }
    if (args.length === 1) {
      if (assertion.value !== null) {
        source.values.push({ relation, value: assertion.value, kind: "attribute", possible });
      } else if (classNames.has(relation)) {
        const list = possible ? source.possibleTypes : source.types;
        if (!list.includes(relation)) {
          list.push(relation);
        }
      } else {
        source.facts.push({ relation, possible });
      }
      continue;
    }
    const literal = literals.get(args[1]);
    if (literal !== undefined) {
      source.values.push({ relation, value: literal, kind: "enum", possible });
      continue;
    }
    const target = nodes.get(args[1]);
    if (target === undefined || assertion.value !== null) {
      omitted.other += 1;
      continue;
    }
    const key = `${possible ? "?" : ""}${relation}\u0000${source.name}\u0000${target.name}`;
    if (linkKeys.has(key)) {
      continue;
    }
    const reverse = linkKeys.get(`${possible ? "?" : ""}${relation}\u0000${target.name}\u0000${source.name}`);
    if (reverse !== undefined && source.name !== target.name) {
      reverse.twoWay = true;
      linkKeys.set(key, reverse);
      continue;
    }
    const link: ModelLink = { relation, source: source.name, target: target.name, possible, twoWay: false };
    linkKeys.set(key, link);
    links.push(link);
  }
  return { nodes: [...nodes.values()], links, omitted, higherArityRelations: [...higherArity] };
}

/** Reads a `.problem` text: its metamodel, its model and its syntax errors. Never throws on any text. */
export function readProblem(text: string): ReadProblem {
  const tree = parser.parse(text);
  const reader = new Reader(text);
  const collected = collect(tree, reader);
  const metamodel = buildMetamodel(collected);
  return { metamodel, model: buildModel(collected, metamodel), syntax: syntaxOf(tree, reader) };
}

/**
 * A relation's name in words, for any name a specification may use: camelCase and underscores split,
 * words of one capital and small letters lower-cased, acronyms kept ("overtakingToPort" reads
 * "overtaking to port", "inCOLREGSSituationWith" reads "in COLREGS situation with"). A qualified
 * name reads as its last part.
 */
export function relationWords(name: string): string {
  const last = name.split("::").pop() ?? name;
  const words = last
    .replace(/_+/g, " ")
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replace(/([A-Z]+)([A-Z][a-z])/g, "$1 $2")
    .split(/\s+/)
    .filter((word) => word.length > 0)
    .map((word) => (/^[A-Z][a-z0-9]*$/.test(word) ? word.toLowerCase() : word));
  return words.length > 0 ? words.join(" ") : last;
}

/** A link in words: "ts1 overtaking to port os", a two-way one once ("os and ts1 head on"), a possible one marked. */
export function describeLink({ relation, source, target, twoWay, possible }: ModelLink): string {
  const words = relationWords(relation);
  const said = twoWay ? `${source} and ${target} ${words}` : `${source} ${words} ${target}`;
  return possible ? `${said} (possibly)` : said;
}

/** "a class", "3 classes": a count with its noun. */
export function counted(count: number, singular: string, plural = `${singular}s`): string {
  return `${count} ${count === 1 ? singular : plural}`;
}
