import { Component, type PropsWithChildren, type ReactNode } from "react";

type ErrorBoundaryState = {
  failed: boolean;
};

export class ErrorBoundary extends Component<
  PropsWithChildren,
  ErrorBoundaryState
> {
  state: ErrorBoundaryState = { failed: false };

  static getDerivedStateFromError(): ErrorBoundaryState {
    return { failed: true };
  }

  render(): ReactNode {
    if (this.state.failed) {
      return (
        <main className="render-failure">
          <section
            className="render-failure__message"
            role="alert"
            aria-labelledby="render-failure-heading"
          >
            <h1 id="render-failure-heading">Interface unavailable</h1>
            <p>
              The operator interface could not be displayed. Reload the page to
              try again.
            </p>
            <p role="note">
              Portfolio simulation only. Do not use for emergency or life-safety
              decisions.
            </p>
          </section>
        </main>
      );
    }

    return this.props.children;
  }
}
