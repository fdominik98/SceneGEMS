import { Position, type NodeHandle } from "@xyflow/react";

/** The handles every card declares (as `CardHandles` draws them), so edges are drawn before, or without, the browser measuring the cards. */
export function cardHandles(width: number): NodeHandle[] {
  return [
    { type: "target", position: Position.Top, x: width / 2, y: 0, width: 1, height: 1 },
    { type: "source", position: Position.Top, x: width / 2, y: 0, width: 1, height: 1 },
  ];
}
