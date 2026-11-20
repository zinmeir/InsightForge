import { useMemo, useState } from 'react';
import { useAuth } from './hooks/useAuth.jsx';
import { useHashRoute } from './hooks/useData.js';
import { TimeRangeContext } from './hooks/useTimeRange.js';
import LoginPage from './components/LoginPage.jsx';
import Layout from './components/Layout.jsx';
import OverviewPage from './components/OverviewPage.jsx';
import ExplorePage from './components/ExplorePage.jsx';
import LiveTailPage from './components/LiveTailPage.jsx';
import AlertsPage from './components/AlertsPage.jsx';
import RulesPage from './components/RulesPage.jsx';

const PAGES = {
  overview: OverviewPage,
  explore: ExplorePage,
  live: LiveTailPage,
  alerts: AlertsPage,
  rules: RulesPage,
};

export default function App() {
  const { session, checking } = useAuth();
  const route = useHashRoute();
  const [range, setRange] = useState('now-1h');
  const [refreshMs, setRefreshMs] = useState(10_000);
  const timeRange = useMemo(() => ({ range, setRange, refreshMs, setRefreshMs }), [range, refreshMs]);

  if (checking) return <div className="splash">Loading…</div>;
  if (!session) return <LoginPage />;

  const Page = PAGES[route.page] ?? OverviewPage;
  return (
    <TimeRangeContext.Provider value={timeRange}>
      <Layout page={route.page in PAGES ? route.page : 'overview'}>
        <Page query={route.query} />
      </Layout>
    </TimeRangeContext.Provider>
  );
}
