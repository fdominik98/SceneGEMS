import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { CatalogDialog } from "./CatalogDialog";
import type { CatalogModel } from "./catalogModel";

// The catalog dialog over a small model: search, filters, groups, and how it opens and closes.

interface Boat {
  id: string;
  name: string;
  size: string;
  fleet: string;
}

const BOATS: Boat[] = [
  { id: "a", name: "Alpha tug", size: "small", fleet: "north" },
  { id: "b", name: "Bravo ferry", size: "large", fleet: "north" },
  { id: "c", name: "Charlie tanker", size: "large", fleet: "south" },
];

const MODEL: CatalogModel<Boat> = {
  idOf: (boat) => boat.id,
  textOf: (boat) => boat.name,
  facets: [
    { key: "size", label: "Size", match: "any", values: (boat) => [{ value: boat.size, label: boat.size }] },
    { key: "fleet", label: "Fleet", match: "any", values: (boat) => [{ value: boat.fleet, label: boat.fleet }] },
  ],
  groupings: [
    { key: "fleet", label: "Fleet", groups: (boat) => [{ value: boat.fleet, label: `${boat.fleet} fleet` }] },
    { key: "size", label: "Size", groups: (boat) => [{ value: boat.size, label: `${boat.size} boats` }] },
  ],
};

function setup(storageKey = "boats") {
  const onClose = vi.fn();
  const { unmount } = render(<CatalogDialog title="Boats" noun="boat" storageKey={storageKey} items={BOATS} model={MODEL} renderItem={(boat) => <button type="button">{boat.name}</button>} onClose={onClose} />);
  return { onClose, unmount, user: userEvent.setup() };
}

const shownBoats = () => screen.queryAllByRole("button", { name: /tug|ferry|tanker/ }).map((button) => button.textContent);

describe("the catalog dialog", () => {
  it("shows the items in the first grouping's groups, and regroups them", async () => {
    const { user } = setup();
    const north = screen.getByRole("region", { name: "north fleet" });
    expect(within(north).getAllByRole("button").map((button) => button.textContent)).toEqual(["Alpha tug", "Bravo ferry"]);
    await user.selectOptions(screen.getByRole("combobox", { name: "Group by" }), "size");
    expect(screen.queryByRole("region", { name: "north fleet" })).not.toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: "large boats" })).getAllByRole("button")).toHaveLength(2);
  });

  it("filters by search and by facets, counts what is left, and clears", async () => {
    const { user } = setup();
    expect(screen.getByRole("status")).toHaveTextContent("3 boats");
    const clear = screen.getByRole("button", { name: "Clear filters" });
    expect(clear).toBeDisabled();

    await user.click(screen.getByRole("checkbox", { name: /large/ }));
    expect(shownBoats()).toEqual(["Bravo ferry", "Charlie tanker"]);
    expect(screen.getByRole("status")).toHaveTextContent("2 of 3 boats");

    await user.type(screen.getByRole("searchbox", { name: "Find a boat" }), "tanker");
    expect(shownBoats()).toEqual(["Charlie tanker"]);

    await user.click(clear);
    expect(shownBoats()).toEqual(["Alpha tug", "Bravo ferry", "Charlie tanker"]);
    expect(screen.getByRole("checkbox", { name: /large/ })).not.toBeChecked();
    expect(screen.getByRole("searchbox", { name: "Find a boat" })).toHaveValue("");
  });

  it("says when nothing matches", async () => {
    const { user } = setup();
    await user.type(screen.getByRole("searchbox", { name: "Find a boat" }), "submarine");
    expect(screen.getByRole("heading", { name: "No boat matches" })).toBeVisible();
    expect(shownBoats()).toEqual([]);
  });

  it("remembers the filters and the grouping per catalog, but not the search", async () => {
    const first = setup();
    await first.user.click(screen.getByRole("checkbox", { name: /small/ }));
    await first.user.selectOptions(screen.getByRole("combobox", { name: "Group by" }), "size");
    await first.user.type(screen.getByRole("searchbox", { name: "Find a boat" }), "alpha");
    first.unmount();

    const second = setup();
    expect(screen.getByRole("checkbox", { name: /small/ })).toBeChecked();
    expect(screen.getByRole("combobox", { name: "Group by" })).toHaveValue("size");
    expect(screen.getByRole("searchbox", { name: "Find a boat" })).toHaveValue("");
    second.unmount();

    setup("other");
    expect(screen.getByRole("checkbox", { name: /small/ })).not.toBeChecked();
  });

  it("ignores stored filters that make no sense any more", () => {
    window.localStorage.setItem("scenegems:wizard-catalog:boats:filters", JSON.stringify({ size: ["gigantic"], fleet: "north" }));
    window.localStorage.setItem("scenegems:wizard-catalog:boats:group-by", JSON.stringify("colour"));
    setup();
    expect(shownBoats()).toEqual(["Alpha tug", "Bravo ferry", "Charlie tanker"]);
    expect(screen.getByRole("button", { name: "Clear filters" })).toBeDisabled();
    expect(screen.getByRole("combobox", { name: "Group by" })).toHaveValue("fleet");
  });

  it("closes on Escape, on the close button and beside the panel, not on a click inside", async () => {
    const { onClose, user } = setup();
    await user.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledTimes(1);
    await user.click(screen.getByRole("button", { name: "Close the catalog" }));
    expect(onClose).toHaveBeenCalledTimes(2);
    await user.click(screen.getByRole("heading", { name: "Boats" }));
    expect(onClose).toHaveBeenCalledTimes(2);
    const dialog = screen.getByRole("dialog", { name: "Boats" });
    await user.click(dialog.parentElement as HTMLElement);
    expect(onClose).toHaveBeenCalledTimes(3);
  });

  it("takes the focus, keeps Tab inside and gives the focus back", async () => {
    function Opener() {
      const [open, setOpen] = useState(false);
      return (
        <>
          <button type="button" onClick={() => setOpen(true)}>
            Open
          </button>
          {open && <CatalogDialog title="Boats" noun="boat" storageKey="focus" items={BOATS} model={MODEL} renderItem={(boat) => <button type="button">{boat.name}</button>} onClose={() => setOpen(false)} />}
        </>
      );
    }
    render(<Opener />);
    const user = userEvent.setup();
    const opener = screen.getByRole("button", { name: "Open" });
    await user.click(opener);
    const search = screen.getByRole("searchbox", { name: "Find a boat" });
    expect(search).toHaveFocus();

    await user.tab({ shift: true });
    const dialog = screen.getByRole("dialog", { name: "Boats" });
    expect(dialog).toContainElement(document.activeElement as HTMLElement);
    expect(screen.getByRole("button", { name: "Charlie tanker" })).toHaveFocus();
    await user.tab();
    expect(search).toHaveFocus();

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(opener).toHaveFocus();
  });
});
