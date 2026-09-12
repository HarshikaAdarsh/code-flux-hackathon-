import { Link } from 'react-router-dom';

export default function NotFoundPage() {
  return (
    <div className="center-pad">
      <p className="mono muted" style={{ fontSize: 13 }}>404</p>
      <h2>That page doesn&apos;t exist</h2>
      <p className="muted">The link may be old, or the subject was deleted.</p>
      <Link className="btn btn-marker" to="/">Back to your subjects</Link>
    </div>
  );
}
