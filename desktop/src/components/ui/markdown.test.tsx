import { render, screen } from "@testing-library/react";
import { Markdown } from "@/components/ui/markdown";

test("renders bold and inline code as elements, not raw markers", () => {
  const { container } = render(<Markdown text={"a **bold** and `code` here"} />);
  expect(container.querySelector("strong")?.textContent).toBe("bold");
  expect(container.querySelector("code")?.textContent).toBe("code");
  // The literal markers are gone.
  expect(container.textContent).not.toContain("**");
});

test("renders a fenced code block verbatim", () => {
  render(<Markdown text={"intro\n```\nline one\nline two\n```"} />);
  const pre = screen.getByText(/line one/);
  expect(pre.tagName).toBe("PRE");
  expect(pre.textContent).toContain("line two");
});

test("renders bullet lists as list items", () => {
  const { container } = render(<Markdown text={"- first\n- second"} />);
  const items = container.querySelectorAll("li");
  expect(items.length).toBe(2);
  expect(items[0].textContent).toBe("first");
});
