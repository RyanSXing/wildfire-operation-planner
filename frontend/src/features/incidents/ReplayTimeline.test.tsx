import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ReplayTimeline } from "./ReplayTimeline";

const START_TIME = "2024-07-24T18:00:00.000Z";
const CURRENT_TIME = "2024-07-24T18:30:00.000Z";
const END_TIME = "2024-07-24T19:00:00.000Z";
const SEEK_TIME = "2024-07-24T18:45:00.000Z";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("ReplayTimeline", () => {
  it("exposes valid native controls and visible UTC context", () => {
    render(
      <ReplayTimeline
        startTime={START_TIME}
        currentTime={CURRENT_TIME}
        endTime={END_TIME}
        playing={false}
        onSeek={vi.fn()}
        onPlayChange={vi.fn()}
      />,
    );

    const range = screen.getByRole("slider", { name: "Replay position" });
    expect(range).toHaveAttribute("type", "range");
    expect(range).toHaveAttribute("min", String(Date.parse(START_TIME)));
    expect(range).toHaveAttribute("max", String(Date.parse(END_TIME)));
    expect(range).toHaveAttribute("value", String(Date.parse(CURRENT_TIME)));
    expect(range).toHaveAttribute(
      "aria-valuetext",
      "2024-07-24 18:30:00 UTC",
    );
    expect(range).toHaveClass("replay-timeline__range");
    expect(
      screen.getByText("Current 2024-07-24 18:30:00 UTC"),
    ).toBeVisible();
    expect(screen.getByText("Start 2024-07-24 18:00:00 UTC")).toBeVisible();
    expect(screen.getByText("End 2024-07-24 19:00:00 UTC")).toBeVisible();

    const play = screen.getByRole("button", { name: "Play" });
    expect(play).toBeEnabled();
    expect(play).toHaveClass("replay-timeline__play-control");
  });

  it("emits the intended canonical UTC timestamp when seeking", () => {
    const onSeek = vi.fn();
    render(
      <ReplayTimeline
        startTime={START_TIME}
        currentTime={CURRENT_TIME}
        endTime={END_TIME}
        playing={false}
        onSeek={onSeek}
        onPlayChange={vi.fn()}
      />,
    );

    fireEvent.change(screen.getByRole("slider", { name: "Replay position" }), {
      target: { value: String(Date.parse(SEEK_TIME)) },
    });

    expect(onSeek).toHaveBeenCalledOnce();
    expect(onSeek).toHaveBeenCalledWith(SEEK_TIME);
  });

  it("requests play and pause changes without owning the playing state", async () => {
    const user = userEvent.setup();
    const onPlayChange = vi.fn();
    const { rerender } = render(
      <ReplayTimeline
        startTime={START_TIME}
        currentTime={CURRENT_TIME}
        endTime={END_TIME}
        playing={false}
        onSeek={vi.fn()}
        onPlayChange={onPlayChange}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Play" }));
    expect(onPlayChange).toHaveBeenLastCalledWith(true);

    rerender(
      <ReplayTimeline
        startTime={START_TIME}
        currentTime={CURRENT_TIME}
        endTime={END_TIME}
        playing
        onSeek={vi.fn()}
        onPlayChange={onPlayChange}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Pause" }));
    expect(onPlayChange).toHaveBeenLastCalledWith(false);
    expect(onPlayChange).toHaveBeenCalledTimes(2);
  });

  it.each([
    { startTime: null, currentTime: null, endTime: null },
    {
      startTime: END_TIME,
      currentTime: CURRENT_TIME,
      endTime: START_TIME,
    },
  ])("disables controls when no usable time range exists", (times) => {
    render(
      <ReplayTimeline
        {...times}
        playing={false}
        onSeek={vi.fn()}
        onPlayChange={vi.fn()}
      />,
    );

    const range = screen.getByRole("slider", { name: "Replay position" });
    expect(range).toBeDisabled();
    expect(range).toHaveAttribute("min", "0");
    expect(range).toHaveAttribute("max", "1");
    expect(range).toHaveAttribute("value", "0");
    expect(range).toHaveAttribute("aria-valuetext", "Replay unavailable");
    expect(screen.getByRole("button", { name: "Play" })).toBeDisabled();
    expect(
      screen.getByText(
        "Replay requires at least two time-ordered snapshots; this incident does not have a usable replay range.",
      ),
    ).toBeVisible();
    expect(screen.getByText("Start unavailable")).toBeVisible();
    expect(screen.getByText("End unavailable")).toBeVisible();
  });

  it("does not start timers or seek as a side effect of playing", () => {
    const setIntervalSpy = vi.spyOn(globalThis, "setInterval");
    const setTimeoutSpy = vi.spyOn(globalThis, "setTimeout");
    const onSeek = vi.fn();

    render(
      <ReplayTimeline
        startTime={START_TIME}
        currentTime={CURRENT_TIME}
        endTime={END_TIME}
        playing
        onSeek={onSeek}
        onPlayChange={vi.fn()}
      />,
    );

    expect(setIntervalSpy).not.toHaveBeenCalled();
    expect(setTimeoutSpy).not.toHaveBeenCalled();
    expect(onSeek).not.toHaveBeenCalled();
  });
});
