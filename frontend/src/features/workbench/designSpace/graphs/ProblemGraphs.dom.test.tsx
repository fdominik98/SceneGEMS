import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ExploredFec } from "../../../../domain/designSpace/explorationResult";
import { DesignSpaceSpecificationEditor } from "../DesignSpaceSpecificationEditor";
import { ExploredFecList } from "../ExploredFecList";
import { useExplorationStore } from "../explorationStore";
import { MetamodelGraph } from "./MetamodelGraph";
import { ModelGraph } from "./ModelGraph";
import { shipColorOfName } from "../../scene/shipColors";

// The graphs of a .problem text with the real grammar, on texts that have nothing to do with ships.

vi.mock("../../../campaigns/useCampaignData", () => ({ useDesignSpaceDefault: () => ({ data: undefined, isSuccess: false, isError: false, error: null }) }));
vi.mock("@uiw/react-codemirror", () => ({
  default: ({ value, readOnly }: { value: string; readOnly?: boolean }) => <textarea aria-label={readOnly ? "FEC text" : "Specification text"} readOnly value={value} />,
}));

const LIBRARY = `abstract class Item {
    string title
}
class Book extends Item {
    Author[1..*] authors opposite books
    Genre[1] genre
}
class Author {
    Book[0..*] books opposite authors
}
class Shelf {
    contains Item[0..*] items
}
enum Genre { Novel, Poetry }
pred prolific(Author a) <-> books(a, _).
error emptyShelf(Shelf s) <-> !items(s, _).
`;

const LIBRARY_MODEL = `${LIBRARY}
declare shelf, dune, frank.
Shelf(shelf). Book(dune). Author(frank).
items(shelf, dune).
authors(dune, frank).
books(frank, dune).
genre(dune, Novel).
?items(shelf, frank).
`;

function fec(index: number): ExploredFec {
  return { fecId: `explored/0000${index}`, index, vesselCount: 0, obstacleCount: 0, artifact: { sha256: String(index).repeat(64), size_bytes: 40, kind: "functional_scenario", media_type: "text/plain", pointer: null } };
}

beforeEach(() => {
  useExplorationStore.getState().clear();
});

describe("the metamodel graph", () => {
  it("draws the classes, enums and references of a specification and lists its predicates and constraints", async () => {
    const user = userEvent.setup();
    render(<MetamodelGraph text={LIBRARY} />);
    expect(screen.getByText("4 classes, 1 enum, 1 predicate, 1 constraint.")).toBeVisible();
    const graph = screen.getByRole("region", { name: "Metamodel graph" });
    for (const name of ["Item", "Book", "Author", "Shelf", "Genre"]) {
      expect(within(graph).getByTitle(name)).toBeVisible();
    }
    expect(within(graph).getByText("abstract")).toBeVisible();
    expect(within(graph).getByRole("list", { name: "Literals of Genre" })).toHaveTextContent("NovelPoetry");
    expect(within(graph).getByRole("list", { name: "Attributes of Book" })).toHaveTextContent("genre: Genre [1]");
    // The opposite pair as one edge with a name at each end, the containment with its own label
    expect(within(graph).getByText("authors [1..*]")).toBeInTheDocument();
    expect(within(graph).getByText("books [0..*]")).toBeInTheDocument();
    expect(within(graph).getByText("items [0..*]")).toBeInTheDocument();
    // The legend is detail: closed until asked for, so the graph has the room
    expect(screen.queryByRole("list", { name: "Legend" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Show the legend" }));
    expect(screen.getByRole("list", { name: "Legend" })).toHaveTextContent("extends: from a class to its superclass");

    await user.click(screen.getByRole("button", { name: "Show the predicates and constraints" }));
    expect(screen.getByRole("list", { name: "Predicates" })).toHaveTextContent("prolific(Author a)");
    expect(screen.getByRole("list", { name: "Constraints (error predicates)" })).toHaveTextContent("emptyShelf(Shelf s)");
  });

  it("says that a text has syntax errors and still draws what it could read", () => {
    render(<MetamodelGraph text={"class Pump {\n  Valve[0..*] valves\n\nclass Valve.\n"} />);
    expect(screen.getByRole("status")).toHaveTextContent(/The text has \d+ syntax errors?, the first on line \d+; the graph shows what could be read\./);
    expect(within(screen.getByRole("region", { name: "Metamodel graph" })).getByTitle("Pump")).toBeVisible();
  });

  it("shows an empty state for an empty text", () => {
    render(<MetamodelGraph text={"  \n"} />);
    expect(screen.getByRole("heading", { name: "Nothing to draw" })).toBeVisible();
    expect(screen.queryByRole("region", { name: "Metamodel graph" })).not.toBeInTheDocument();
  });
});

describe("the model graph", () => {
  it("draws the objects with their types and values and the links with their relation", () => {
    render(<ModelGraph text={LIBRARY_MODEL} />);
    expect(screen.getByText("3 objects, 4 links, 1 of them possible.")).toBeVisible();
    const graph = screen.getByRole("region", { name: "Model graph" });
    expect(within(graph).getByTitle("dune")).toBeVisible();
    // A row per class the object is, then its values, under its name
    expect(within(graph).getByTitle("dune is a Book")).toBeVisible();
    expect(within(graph).getByRole("list", { name: "What dune is" })).toHaveTextContent("Book");
    expect(within(graph).getByRole("list", { name: "What dune is" })).toHaveTextContent("genre: Novel");
    // The pair authors and books is two relations, so two edges; the unknown one is drawn too
    expect(within(graph).getByText("authors")).toBeInTheDocument();
    expect(within(graph).getAllByText("items")).toHaveLength(2);
    // The metamodel the text repeats is not drawn
    expect(within(graph).queryByTitle("Genre")).not.toBeInTheDocument();
  });

  it("says when a text has no objects", () => {
    render(<ModelGraph text={LIBRARY} />);
    expect(screen.getByRole("heading", { name: "No objects" })).toBeVisible();
  });
});

describe("the switches", () => {
  it("shows the specification as a graph and remembers the choice", async () => {
    const user = userEvent.setup();
    const props = { value: LIBRARY, label: null, onEdit: vi.fn(), onLoad: vi.fn() };
    const { unmount } = render(<DesignSpaceSpecificationEditor {...props} />);
    expect(screen.getByRole("button", { name: "Text" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByRole("region", { name: "Metamodel graph" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Graph" }));
    expect(screen.getByRole("button", { name: "Graph" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("region", { name: "Metamodel graph" })).toBeVisible();
    // The editor's tools stay
    expect(screen.getByRole("button", { name: "Open file..." })).toBeVisible();
    expect(window.localStorage.getItem("scenegems:design-space-specification-view")).toBe('"graph"');

    unmount();
    render(<DesignSpaceSpecificationEditor {...props} />);
    expect(screen.getByRole("region", { name: "Metamodel graph" })).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Text" }));
    expect(screen.getByLabelText("Specification text")).toBeVisible();
  });

  it("follows an edited specification after a pause", async () => {
    window.localStorage.setItem("scenegems:design-space-specification-view", '"graph"');
    const props = { label: null, onEdit: vi.fn(), onLoad: vi.fn() };
    const { rerender } = render(<DesignSpaceSpecificationEditor value="class Alpha." {...props} />);
    expect(screen.getByTitle("Alpha")).toBeVisible();
    rerender(<DesignSpaceSpecificationEditor value={"class Alpha.\nclass Beta."} {...props} />);
    await waitFor(() => expect(screen.getByTitle("Beta")).toBeVisible());
  });

  it("shows the selected FEC as its model graph first, its text one click away, and remembers the choice", async () => {
    const user = userEvent.setup();
    useExplorationStore.getState().show({ campaignId: "c1", result: { stop_reason: "exhausted", models_found: 1 }, fecs: [fec(0)], selectedFecId: "explored/00000" });
    useExplorationStore.getState().textLoaded("explored/00000", LIBRARY_MODEL);
    const { unmount } = render(<ExploredFecList client={null} />);
    expect(screen.getByRole("button", { name: "Graph" })).toHaveAttribute("aria-pressed", "true");
    expect(within(screen.getByRole("region", { name: "Model graph of explored/00000" })).getByTitle("frank")).toBeVisible();
    // The row says its relations with the specification's names
    expect(screen.getByRole("option", { name: /explored\/00000/ })).toHaveTextContent("shelf items dune; dune authors frank; frank books dune; shelf items frank (possibly)");
    await user.click(screen.getByRole("button", { name: "Text" }));
    expect(screen.getByLabelText("FEC text")).toHaveValue(LIBRARY_MODEL);
    unmount();
    render(<ExploredFecList client={null} />);
    expect(screen.getByRole("button", { name: "Text" })).toHaveAttribute("aria-pressed", "true");
  });
});

describe("the colors of the objects", () => {
  const SHIPS = `class Vessel.
class OS extends Vessel.
class TS extends Vessel.
class Buoy.
declare os, tS1, ts2, marker.
OS(os).
TS(tS1).
TS(ts2).
Buoy(marker).
`;

  it("gives a vessel the color it has everywhere else in the console, whatever the case of its id", () => {
    render(<ModelGraph text={SHIPS} />);
    const colorOf = (name: string) => (screen.getByTitle(name).closest(".pg-card") as HTMLElement).style.getPropertyValue("--pg-node-color");
    expect(colorOf("os")).toBe(shipColorOfName("os", "dark"));
    expect(colorOf("tS1")).toBe(shipColorOfName("ts1", "dark"));
    expect(colorOf("ts2")).toBe(shipColorOfName("ts2", "dark"));
    expect(new Set([colorOf("os"), colorOf("tS1"), colorOf("ts2")]).size).toBe(3);
    // any other object takes the tone of its class instead
    expect(colorOf("marker")).toBe("");
    expect(screen.getByTitle("marker").closest(".pg-card")).toHaveClass(/pg-tone-\d/);
  });
});
