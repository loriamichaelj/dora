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
  /** A CSS color; a token such as `var(--chart-2)` follows the theme. */
  color: string;
  /** Dashed, so two lines differ by more than color. */
  dashed?: boolean;
}

const TICK = { fill: 'var(--color-muted)', fontSize: 12 };
const AXIS_LINE = { stroke: 'var(--chart-axis)' };
const TOOLTIP_STYLE = {
  background: 'var(--color-surface)',
  border: '1px solid var(--color-border)',
  borderRadius: 8,
  boxShadow: 'var(--shadow-md)',
  color: 'var(--color-text)',
  fontSize: 13,
};

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
        <ResponsiveContainer width="100%" height={220}>
          <Chart data={[...points]} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid stroke="var(--chart-grid)" vertical={false} />
            <XAxis
              dataKey="start"
              tickFormatter={formatBucket}
              tick={TICK}
              axisLine={AXIS_LINE}
              tickLine={false}
              minTickGap={16}
            />
            <YAxis
              width={48}
              tick={TICK}
              axisLine={false}
              tickLine={false}
              tickFormatter={(v: number) => axisFormat(v)}
            />
            <Tooltip
              contentStyle={TOOLTIP_STYLE}
              labelStyle={{ fontWeight: 600, marginBottom: 4 }}
              cursor={{ fill: 'var(--color-surface-2)', stroke: 'var(--chart-axis)' }}
              labelFormatter={(label) =>
                typeof label === 'string' ? `Week of ${formatBucket(label)}` : ''
              }
              formatter={(value) => display(value, format)}
            />
            {series.length > 1 && (
              <Legend
                iconType="plainline"
                wrapperStyle={{ color: 'var(--color-muted)', fontSize: 12, paddingTop: 4 }}
              />
            )}
            {series.map((s) =>
              kind === 'bar' ? (
                <Bar
                  key={s.key}
                  dataKey={s.key}
                  name={s.label}
                  fill={s.color}
                  radius={[4, 4, 0, 0]}
                  maxBarSize={28}
                />
              ) : (
                <Line
                  key={s.key}
                  dataKey={s.key}
                  name={s.label}
                  stroke={s.color}
                  strokeWidth={2}
                  {...(s.dashed ? { strokeDasharray: '5 4' } : {})}
                  dot={{ r: 2.5, fill: s.color, strokeWidth: 0 }}
                  activeDot={{ r: 4, strokeWidth: 0 }}
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
