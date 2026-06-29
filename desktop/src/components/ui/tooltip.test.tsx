import { render, screen, fireEvent } from "@testing-library/react";
import { InfoDot } from "@/components/ui/tooltip";

test("clicking the info dot reveals its explanation", () => {
  render(<InfoDot label="what this means" />);
  expect(screen.queryByRole("tooltip")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "what this means" }));
  expect(screen.getByRole("tooltip")).toHaveTextContent("what this means");
});
