import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

import { formatBucket, NO_VALUE } from '../lib/format';
import styles from './TrendChart.module.css';

export interface Series {
  key: string;
  label: string;
  color: string;
}

interface Props {
  title: string;
  kind: 'bar' | 'line';
  points: readonly Record<string, unknown>[];
  series: readonly Series[];
  /** Values in tooltips and the accessible table. */
  format: (value: number) => string;
  /** Axis ticks: one fixed unit so the scale reads consistently. */
  axisFormat?: (value: number) => string;
}

function display(value: unknown, format: (value: number) => string): string {
  return typeof value === 'number' ? format(value) : NO_VALUE;
}

/**
 * A weekly trend. Screen readers get the same numbers as a table, since a
 * chart alone isn't accessible (§8).
 */
export function TrendChart({ title, kind, points, series, format, axisFormat = format }: Props) {
  const Chart = kind === 'bar' ? BarChart : LineChart;
  return (
    <figure className={styles.figure}>
      <figcaption className={styles.caption}>{title}</figcaption>
      <div className={styles.plot} aria-hidden="true">
        <ResponsiveContainer width="100%" height={200}>
          <Chart data={[...points]} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" vertical={false} />
            <XAxis dataKey="start" tickFormatter={formatBucket} fontSize={12} />
            <YAxis width={48} fontSize={12} tickFormatter={(v: number) => axisFormat(v)} />
            <Tooltip
              labelFormatter={(label) =>
                typeof label === 'string' ? `Week of ${formatBucket(label)}` : ''
              }
              formatter={(value) => display(value, format)}
            />
            {series.length > 1 && <Legend />}
            {series.map((s) =>
              kind === 'bar' ? (
                <Bar key={s.key} dataKey={s.key} name={s.label} fill={s.color} />
              ) : (
                <Line
                  key={s.key}
                  dataKey={s.key}
                  name={s.label}
                  stroke={s.color}
                  strokeWidth={2}
                  dot={{ r: 3 }}
                  connectNulls={false}
                  isAnimationActive={false}
                />
              ),
            )}
          </Chart>
        </ResponsiveContainer>
      </div>
      <table className="visually-hidden">
        <caption>{title}</caption>
        <thead>
          <tr>
            <th scope="col">Week of</th>
            {series.map((s) => (
              <th key={s.key} scope="col">
                {s.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {points.map((point) => (
            <tr key={String(point.start)}>
              <th scope="row">{formatBucket(String(point.start))}</th>
              {series.map((s) => (
                <td key={s.key}>{display(point[s.key], format)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </figure>
  );
}
