import { describeLink, readProblem } from "./problemModel";

/**
 * The relations of an explored FEC in words, for its row in the list. A FEC's text is a complete
 * `.problem` text; its links are read from the syntax tree (`problemModel.ts`) and said with the
 * relation names the specification uses ("ts1 overtaking to port os"), a link in both directions
 * once ("os and ts1 head on"). Values (an enum literal, an attribute) are left out to keep the row
 * short; the model graph shows them on their object.
 */

/** Rows of a long list ask again on every render; the summaries of the last texts are kept. */
const CACHE_SIZE = 600;
const cache = new Map<string, string>();

/** Every link of a FEC's text in words, separated by semicolons; "no relations" when it has none. */
export function fecRelationSummary(text: string): string {
  const known = cache.get(text);
  if (known !== undefined) {
    return known;
  }
  const links = readProblem(text).model.links;
  const summary = links.length === 0 ? "no relations" : links.map(describeLink).join("; ");
  if (cache.size >= CACHE_SIZE) {
    const oldest = cache.keys().next().value;
    if (oldest !== undefined) {
      cache.delete(oldest);
    }
  }
  cache.set(text, summary);
  return summary;
}
