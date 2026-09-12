import { Component } from 'react';

/**
 * Catches render-time crashes so a single bad component shows a recoverable
 * message instead of a blank white page.
 */
export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    // Keep the full trace in the console for whoever is debugging.
    console.error('Unhandled UI error:', error, info?.componentStack);
  }

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;

    return (
      <div className="center-pad">
        <h2>Something broke on this screen</h2>
        <p className="muted" style={{ maxWidth: 460 }}>
          The rest of the app is fine. Reloading usually clears it — your work is
          saved on the server, not in the page.
        </p>
        <pre
          style={{
            maxWidth: 560,
            overflow: 'auto',
            fontSize: 12,
            background: 'var(--border-dark)',
            color: '#E8EAF2',
            padding: '12px 14px',
            borderRadius: 10,
            textAlign: 'left',
          }}
        >
          {String(error?.message || error)}
        </pre>
        <div className="row gap8">
          <button className="btn btn-marker" onClick={() => window.location.reload()} type="button">
            Reload
          </button>
          <button
            className="btn btn-ghost"
            onClick={() => {
              this.setState({ error: null });
              window.location.assign('/');
            }}
            type="button"
          >
            Back to subjects
          </button>
        </div>
      </div>
    );
  }
}
