import { memo, useEffect, useId, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

/**
 * Lessons come back as markdown, and the tutor is prompted to emit mermaid
 * diagrams for structural concepts (PRD 7.2). Mermaid is loaded lazily so the
 * ~2MB bundle only costs anything once a diagram actually appears.
 */
let mermaidPromise = null;
function loadMermaid() {
  if (!mermaidPromise) {
    mermaidPromise = import('mermaid').then((m) => {
      const mermaid = m.default;
      mermaid.initialize({
        startOnLoad: false,
        securityLevel: 'strict',
        theme: 'base',
        fontFamily: '"Onest", system-ui, sans-serif',
        themeVariables: {
          primaryColor: '#E7ECFB',
          primaryTextColor: '#191C28',
          primaryBorderColor: '#22409A',
          lineColor: '#666B7A',
          secondaryColor: '#FFE94A',
          tertiaryColor: '#F6F5EF',
        },
      });
      return mermaid;
    });
  }
  return mermaidPromise;
}

function MermaidBlock({ code }) {
  const domId = `mmd-${useId().replace(/[:»]/g, '')}`;
  const [svg, setSvg] = useState('');
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let alive = true;
    setFailed(false);
    setSvg('');
    loadMermaid()
      .then((mermaid) => mermaid.render(domId, code))
      .then(({ svg: out }) => {
        if (alive) setSvg(out);
      })
      .catch(() => {
        if (alive) setFailed(true);
      });
    return () => {
      alive = false;
    };
  }, [code, domId]);

  // A malformed diagram should never hide the lesson — show the source.
  if (failed) {
    return (
      <div className="mermaid-box">
        <p className="mermaid-err">Diagram couldn&apos;t be drawn. Source:</p>
        <pre>
          <code>{code}</code>
        </pre>
      </div>
    );
  }
  if (!svg) return <div className="mermaid-box mermaid-err">Drawing diagram…</div>;
  // eslint-disable-next-line react/no-danger -- mermaid output, securityLevel: strict
  return <div className="mermaid-box" dangerouslySetInnerHTML={{ __html: svg }} />;
}

const components = {
  code({ inline, className, children, ...props }) {
    const text = String(children).replace(/\n$/, '');
    if (!inline && /language-mermaid/.test(className || '')) {
      return <MermaidBlock code={text} />;
    }
    return (
      <code className={className} {...props}>
        {children}
      </code>
    );
  },
  a: ({ children, ...props }) => (
    <a {...props} target="_blank" rel="noreferrer noopener">
      {children}
    </a>
  ),
};

function Markdown({ children }) {
  return (
    <div className="md">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {children || ''}
      </ReactMarkdown>
    </div>
  );
}

export default memo(Markdown);
