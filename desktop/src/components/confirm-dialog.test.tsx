import { render, screen, fireEvent } from "@testing-library/react";
import { ConfirmDialog } from "@/components/confirm-dialog";

test("renders nothing when closed", () => {
  const { container } = render(
    <ConfirmDialog open={false} title="Stop?" onConfirm={() => {}} onCancel={() => {}} />,
  );
  expect(container).toBeEmptyDOMElement();
});

test("confirm and cancel fire their callbacks", () => {
  const onConfirm = vi.fn();
  const onCancel = vi.fn();
  render(
    <ConfirmDialog
      open
      title="Stop this session?"
      confirmLabel="Stop (SIGTERM)"
      onConfirm={onConfirm}
      onCancel={onCancel}
    >
      <p>pid 1234</p>
    </ConfirmDialog>,
  );

  expect(screen.getByText("pid 1234")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Stop (SIGTERM)" }));
  expect(onConfirm).toHaveBeenCalledTimes(1);

  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(onCancel).toHaveBeenCalledTimes(1);
});

test("Escape cancels the dialog", () => {
  const onCancel = vi.fn();
  render(
    <ConfirmDialog open title="Stop?" onConfirm={() => {}} onCancel={onCancel}>
      <p>body</p>
    </ConfirmDialog>,
  );
  fireEvent.keyDown(window, { key: "Escape" });
  expect(onCancel).toHaveBeenCalledTimes(1);
});
