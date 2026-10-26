import http from 'k6/http';
import { check, sleep } from 'k6';
import { Trend, Counter } from 'k6/metrics';

const healthDuration = new Trend('health_req_duration');
const listMonitorsDuration = new Trend('list_monitors_duration');
const createMonitorDuration = new Trend('create_monitor_duration');
const successfulActions = new Counter('successful_actions');

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8000';

export const options = {
  scenarios: {
    // Stage 1: Quick warm-up to confirm service readiness
    warmup: {
      executor: 'constant-vus',
      vus: 10,
      duration: '15s',
      startTime: '0s',
      tags: { scenario: 'warmup' },
    },
    // Stage 2: Ramping arrival rate to achieve >2,000 RPS
    throughput_benchmark: {
      executor: 'ramping-arrival-rate',
      startRate: 200,
      timeUnit: '1s',
      preAllocatedVUs: 200,
      maxVUs: 1500,
      stages: [
        { duration: '30s', target: 800 },
        { duration: '1m', target: 2000 },
        { duration: '2m', target: 2500 },
        { duration: '30s', target: 200 },
      ],
      startTime: '20s',
      tags: { scenario: 'throughput_benchmark' },
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.01'],
    http_req_duration: ['p(95)<200', 'p(99)<500'],
    health_req_duration: ['p(95)<50'],
    list_monitors_duration: ['p(95)<200'],
  },
};

export function setup() {
  const timestamp = Date.now();
  const testUser = {
    email: `k6_tester_${timestamp}@example.com`,
    password: 'Password123!@#',
  };

  const registerRes = http.post(
    `${BASE_URL}/api/v1/auth/register`,
    JSON.stringify(testUser),
    { headers: { 'Content-Type': 'application/json' } }
  );

  let token = null;
  if (registerRes.status === 201) {
    token = registerRes.json('access_token');
  } else {
    const loginRes = http.post(
      `${BASE_URL}/api/v1/auth/login`,
      JSON.stringify(testUser),
      { headers: { 'Content-Type': 'application/json' } }
    );
    token = loginRes.json('access_token');
  }

  if (!token) {
    throw new Error('Failed to acquire authentication token in setup phase');
  }

  const authHeaders = {
    'Content-Type': 'application/json',
    Authorization: `Bearer ${token}`,
  };

  const monitorIds = [];
  for (let i = 1; i <= 5; i++) {
    const payload = JSON.stringify({
      name: `K6 Seed Monitor ${i}`,
      url: `https://example.com/target-${i}`,
      method: 'GET',
      interval_seconds: 30,
      timeout_seconds: 5,
      expected_status_code: 200,
      consecutive_threshold: 3,
      is_active: true,
    });
    const res = http.post(`${BASE_URL}/api/v1/monitors`, payload, {
      headers: authHeaders,
    });
    if (res.status === 201) {
      monitorIds.push(res.json('id'));
    }
  }

  return { token, monitorIds };
}

export default function (data) {
  const authHeaders = {
    'Content-Type': 'application/json',
    Authorization: `Bearer ${data.token}`,
  };

  const rand = Math.random();

  if (rand < 0.45) {
    // 45% of traffic: Lightweight gateway health check
    const res = http.get(`${BASE_URL}/health`);
    healthDuration.add(res.timings.duration);
    const passed = check(res, {
      'health status is 200': (r) => r.status === 200,
    });
    if (passed) successfulActions.add(1);
  } else if (rand < 0.85) {
    // 40% of traffic: Authenticated monitor listing with pagination
    const res = http.get(`${BASE_URL}/api/v1/monitors?limit=20&offset=0`, {
      headers: authHeaders,
    });
    listMonitorsDuration.add(res.timings.duration);
    const passed = check(res, {
      'list monitors status is 200': (r) => r.status === 200,
      'list returned array': (r) => Array.isArray(r.json()),
    });
    if (passed) successfulActions.add(1);
  } else if (rand < 0.95 && data.monitorIds.length > 0) {
    // 10% of traffic: Monitor detail query with recent check history
    const targetId = data.monitorIds[Math.floor(Math.random() * data.monitorIds.length)];
    const res = http.get(`${BASE_URL}/api/v1/monitors/${targetId}`, {
      headers: authHeaders,
    });
    const passed = check(res, {
      'get monitor detail status is 200': (r) => r.status === 200,
    });
    if (passed) successfulActions.add(1);
  } else {
    // 5% of traffic: Monitor creation triggering DB insertion and Redis ZADD
    const uniqueSuffix = `${__VU}_${__ITER}_${Date.now()}`;
    const payload = JSON.stringify({
      name: `K6 Dynamic Target ${uniqueSuffix}`,
      url: `https://example.com/check-${uniqueSuffix}`,
      method: 'GET',
      interval_seconds: 60,
      timeout_seconds: 5,
      expected_status_code: 200,
      consecutive_threshold: 3,
      is_active: false,
    });
    const res = http.post(`${BASE_URL}/api/v1/monitors`, payload, {
      headers: authHeaders,
    });
    createMonitorDuration.add(res.timings.duration);
    const passed = check(res, {
      'create monitor status is 201': (r) => r.status === 201,
    });
    if (passed) successfulActions.add(1);
  }

  sleep(0.01);
}
