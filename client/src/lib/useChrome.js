import { useEffect } from 'react';
import { useOutletContext } from 'react-router-dom';

/**
 * Lets a page publish its breadcrumb and focus-session scope to the top bar.
 * `crumb` is JSX; `scope` is {subjectId, subtopicId} for the Pomodoro widget.
 */
export function useChrome(crumb, scope, deps = []) {
  const { setCrumb, setScope } = useOutletContext() || {};

  useEffect(() => {
    setCrumb?.(crumb);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  useEffect(() => {
    setScope?.(scope || {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scope?.subjectId, scope?.subtopicId]);
}
