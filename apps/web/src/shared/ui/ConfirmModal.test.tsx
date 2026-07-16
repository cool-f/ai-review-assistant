import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";

import ConfirmModal from "./ConfirmModal";


test("a confirmed business action is reported to its caller", async () => {
  const user = userEvent.setup();
  const onConfirm = vi.fn();

  render(
    <ConfirmModal
      open
      title="确认上传"
      message="开始处理课件"
      onConfirm={onConfirm}
      onCancel={() => undefined}
    />,
  );

  await user.click(screen.getByRole("button", { name: "确认" }));

  expect(onConfirm).toHaveBeenCalledOnce();
});
