import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { App } from "./App";

describe("App", () => {
  it("renders the login screen by default", () => {
    render(<App />);
    expect(screen.getByText("SP2 Assistant")).toBeTruthy();
  });
});
