import { createContext, useContext } from 'react';

export const TimeRangeContext = createContext(null);

export function useTimeRange() {
  const ctx = useContext(TimeRangeContext);
  if (!ctx) throw new Error('useTimeRange must be used inside <TimeRangeContext.Provider>');
  return ctx;
}
