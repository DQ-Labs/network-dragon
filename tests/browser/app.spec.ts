import { test, expect, type Page } from '../../frontend/node_modules/@playwright/test';

async function signIn(page: Page) {
  const password = process.env.DRAGON_TEST_PASSWORD;
  if (!password) throw new Error('Set DRAGON_TEST_PASSWORD for the isolated fixture database');
  await page.goto('/');
  await page.getByLabel('Administrator password', { exact: true }).fill(password);
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page.getByRole('heading', { level: 1, name: 'Fixture lab' })).toBeVisible();
}

const deviceRow = (page: Page, name: string) => page.locator('tbody tr').filter({ has: page.getByRole('link', { name: new RegExp(name) }) });

test('authenticated fixture inventory, quiet history, and administration', async ({ page }) => {
  await signIn(page);
  await expect(page.getByText('Fixture workspace', { exact: true })).toBeVisible();
  await page.setViewportSize({ width: 1440, height: 1100 });
  await page.screenshot({ path: '../artifacts/overview-desktop.png', fullPage: true });
  await page.getByRole('navigation', { name: 'Main navigation' }).getByRole('link', { name: 'Devices' }).click();
  await page.getByRole('link', { name: /compute-01.lab|Fixture compute node/ }).click();
  await expect(page.getByRole('heading', { name: 'Last-known TCP ports' })).toBeVisible();
  await expect(page.getByText('Closed', { exact: true })).toBeVisible();
  await page.getByLabel('Display name').fill('Fixture compute node');
  await page.getByRole('button', { name: 'Save details' }).click();
  await expect(page.getByRole('heading', { name: 'Fixture compute node' })).toBeVisible();
  await page.getByLabel('Display name').fill('');
  await page.getByRole('button', { name: 'Save details' }).click();
  await expect(page.getByRole('heading', { name: 'compute-01.lab' })).toBeVisible();
  await page.goto('/activity?category=ports');
  await page.getByRole('searchbox', { name: 'Search event evidence' }).fill('8080');
  await expect(page.getByText('Port state changed · 8080/tcp', { exact: true })).toBeVisible();
  await expect(page.getByText('Port state changed · 3000/tcp', { exact: true })).not.toBeVisible();
  await page.goto('/notifications');
  await expect(page.getByText('Port and service changes never notify.', { exact: true })).toBeVisible();
  await page.goto('/scans');
  await expect(page.getByRole('button', { name: 'Queue scan' })).toBeDisabled();
  await page.goto('/settings');
  await expect(page.getByRole('heading', { name: 'Access & boundaries' })).toBeVisible();
  await page.goto('/');
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole('heading', { name: 'Port & service changes' })).toBeVisible();
  await page.screenshot({ path: '../artifacts/overview-mobile.png', fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.getByRole('button', { name: 'Toggle color theme' }).click();
  await page.screenshot({ path: '../artifacts/overview-toggled-theme-mobile.png', fullPage: true });
  await page.getByRole('button', { name: 'Toggle navigation' }).click();
  await page.getByRole('button', { name: 'Sign out' }).click();
  await expect(page.getByRole('button', { name: 'Sign in', exact: true })).toBeVisible();
});

test('untrusted hostname is rendered as text', async ({ page }) => {
  await signIn(page);
  await page.goto('/devices');
  await page.getByRole('link', { name: /storage.lab/ }).click();
  const payload = '<img src=x onerror="window.dragonXss=true">';
  await page.getByLabel('Display name').fill(payload);
  await page.getByRole('button', { name: 'Save details' }).click();
  await expect(page.getByRole('heading', { name: payload })).toBeVisible();
  expect(await page.evaluate(() => (window as any).dragonXss)).toBeUndefined();
  await page.getByLabel('Display name').fill('');
  await page.getByRole('button', { name: 'Save details' }).click();
  await expect(page.getByRole('heading', { name: 'storage.lab' })).toBeVisible();
});

test('pagination follows the page size returned by the API', async ({ page }) => {
  await signIn(page);
  await page.route('**/api/v1/events?**', async route => {
    const offset = Number(new URL(route.request().url()).searchParams.get('offset') || 0);
    await route.fulfill({ json: { items: [], total: 5, offset, limit: 2 } });
  });
  await page.goto('/activity');
  await expect(page.getByText('1–2 of 5', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Previous', exact: true })).toBeDisabled();
  await page.getByRole('button', { name: 'Next', exact: true }).click();
  await expect(page.getByText('3–4 of 5', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Next', exact: true }).click();
  await expect(page.getByText('5–5 of 5', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Next', exact: true })).toBeDisabled();
  await page.getByRole('button', { name: 'Previous', exact: true }).click();
  await expect(page.getByText('3–4 of 5', { exact: true })).toBeVisible();
});

test('device inventory loads every API page and sorts IP addresses numerically', async ({ page }) => {
  await signIn(page);
  const device = (ip: string) => ({ id: ip, network_id: 'n', ip, mac: null, name: '', hostname: `host-${ip.split('.')[3]}`, presence: 'online', monitored: true, acknowledged: true, watched: false, archived: false, stale: false, open_ports: 0, last_seen: Date.now() / 1000, first_seen: 0 });
  const all = ['192.0.2.100', '192.0.2.9', '192.0.2.10'].map(device);
  await page.route('**/api/v1/devices?**', async route => {
    const offset = Number(new URL(route.request().url()).searchParams.get('offset') || 0);
    await route.fulfill({ json: { items: all.slice(offset, offset + 2), total: all.length, offset, limit: 2 } });
  });
  await page.goto('/devices');
  await expect(page.getByText('Showing 3 of 3 active devices')).toBeVisible();
  await expect(page.locator('tbody tr strong')).toHaveText(['host-9', 'host-10', 'host-100']);
  await page.getByRole('button', { name: 'IP address' }).click();
  await expect(page.getByRole('columnheader', { name: 'IP address' })).toHaveAttribute('aria-sort', 'descending');
  await expect(page.locator('tbody tr strong')).toHaveText(['host-100', 'host-10', 'host-9']);
});

test('overview answers the morning questions and guides baseline review', async ({ page }) => {
  await signIn(page);
  const baseline = page.getByRole('region', { name: /Baseline review in progress/ });
  await expect(baseline).toBeVisible();
  await expect(baseline.getByRole('link', { name: '2 awaiting review' })).toBeVisible();
  // Finishing the review needs an explicit confirmation; cancel leaves it in review.
  await baseline.getByRole('button', { name: 'Finish baseline review…' }).click();
  await expect(baseline.getByRole('button', { name: 'Finish review & enable delivery' })).toBeVisible();
  await baseline.getByRole('button', { name: 'Cancel' }).click();
  await expect(baseline.getByRole('button', { name: 'Finish baseline review…' })).toBeVisible();
  // Scanner freshness shows relative time with the exact value kept on hover.
  const scanner = page.getByRole('link', { name: /^Scanner/ });
  await expect(scanner).toContainText(/Discovery (.*ago|just now)/);
  const stamp = scanner.locator('time').first();
  await expect(stamp).toHaveAttribute('datetime', /^\d{4}-\d\d-\d\dT/);
  expect(await stamp.getAttribute('title')).toMatch(/\d/);
  // Port changes name the device they happened on.
  const ports = page.locator('section.panel').filter({ has: page.getByRole('heading', { name: 'Port & service changes' }) });
  await expect(ports.getByText('Port state changed · 3000/tcp')).toBeVisible();
  await expect(ports.getByRole('link', { name: 'compute-01.lab' }).first()).toBeVisible();
  // Unreviewed devices are listed by name, and the tile filters the inventory.
  const attention = page.locator('section.panel').filter({ has: page.getByRole('heading', { name: 'Needs attention' }) });
  await expect(attention.getByText('Needs review')).toHaveCount(2);
  await page.getByRole('link', { name: /^Needs review 2/ }).click();
  await expect(page).toHaveURL(/\/devices\?view=review$/);
  await expect(page.getByRole('heading', { level: 1, name: 'Devices' })).toBeFocused();
  await expect(page.getByRole('button', { name: /^Needs review/ })).toHaveAttribute('aria-pressed', 'true');
  await expect(page.locator('tbody tr')).toHaveCount(2);
  await expect(deviceRow(page, 'workstation.lab')).toBeVisible();
  await expect(deviceRow(page, 'home-bridge.lab')).toBeVisible();
});

test('acknowledge and watch from the device list, undo from the detail page', async ({ page }) => {
  await signIn(page);
  await page.goto('/devices?view=review');
  await page.getByRole('button', { name: 'Acknowledge workstation.lab' }).click();
  await expect(page.getByRole('status')).toContainText('workstation.lab acknowledged');
  await expect(deviceRow(page, 'workstation.lab')).toHaveCount(0);
  await expect(page.getByRole('button', { name: /^Needs review/ })).toContainText('1');
  await page.getByRole('button', { name: /^All/ }).click();
  const watch = page.getByRole('button', { name: 'Watch home-bridge.lab' });
  await expect(watch).toHaveAttribute('aria-pressed', 'false');
  await watch.click();
  await expect(watch).toHaveAttribute('aria-pressed', 'true');
  await expect(deviceRow(page, 'home-bridge.lab').getByText('Watched')).toBeVisible();
  await watch.click();
  await expect(watch).toHaveAttribute('aria-pressed', 'false');
  await page.getByRole('link', { name: /workstation.lab/ }).click();
  const acknowledged = page.getByRole('button', { name: 'Acknowledged' });
  await expect(acknowledged).toHaveAttribute('aria-pressed', 'true');
  await acknowledged.click();
  await expect(page.getByRole('status')).toContainText('marked as awaiting review');
  await expect(page.getByRole('button', { name: 'Acknowledge', exact: true })).toBeVisible();
  await expect(page.getByText('Needs review', { exact: true })).toBeVisible();
});

test('device detail quick actions: mute, archive, and notes', async ({ page }) => {
  await signIn(page);
  await page.goto('/devices');
  await page.getByRole('link', { name: /gateway.lab/ }).click();
  await expect(page.getByRole('group', { name: 'Device actions' })).toBeVisible();
  await page.getByText('Mute…').click();
  await page.getByRole('button', { name: 'Mute for 8 hours' }).click();
  const unmute = page.getByRole('button', { name: /Unmute/ });
  await expect(unmute).toBeVisible();
  await expect(unmute.locator('time')).toHaveAttribute('title', /\d/);
  await expect(page.locator('.device-flags').getByText('Muted')).toBeVisible();
  await unmute.click();
  await expect(page.getByText('Mute…')).toBeVisible();
  await page.getByRole('button', { name: 'Archive', exact: true }).click();
  await expect(page.locator('.device-flags').getByText('Archived')).toBeVisible();
  await page.getByRole('link', { name: '← All devices' }).click();
  await expect(page.getByRole('link', { name: /gateway.lab/ })).toHaveCount(0);
  await page.getByRole('button', { name: /^Archived/ }).click();
  await page.getByRole('link', { name: /gateway.lab/ }).click();
  await page.getByRole('button', { name: 'Unarchive' }).click();
  await expect(page.getByRole('button', { name: 'Archive', exact: true })).toBeVisible();
  await page.getByLabel('Notes').fill('Rack 2, upstream router');
  await page.getByRole('button', { name: 'Save details' }).click();
  await expect(page.getByRole('status')).toContainText('Name and notes saved');
  await page.goto('/devices');
  await page.getByRole('searchbox', { name: 'Search devices' }).fill('rack 2');
  await expect(page.locator('tbody tr')).toHaveCount(1);
  await page.getByRole('link', { name: /gateway.lab/ }).click();
  await page.getByLabel('Notes').fill('');
  await page.getByRole('button', { name: 'Save details' }).click();
  await expect(page.getByRole('status')).toContainText('Name and notes saved');
});

test('keyboard search, column sorting, and navigation landmarks', async ({ page }) => {
  await signIn(page);
  await page.keyboard.press('Tab');
  await expect(page.getByRole('link', { name: 'Skip to content' })).toBeFocused();
  await page.goto('/devices');
  await expect(page.getByRole('link', { name: 'Devices', exact: true })).toHaveAttribute('aria-current', 'page');
  await page.locator('body').press('/');
  const search = page.getByRole('searchbox', { name: 'Search devices' });
  await expect(search).toBeFocused();
  await page.keyboard.type('compute');
  await expect(page.locator('tbody tr')).toHaveCount(2);
  await search.fill('');
  await page.getByRole('button', { name: 'Device', exact: true }).click();
  await expect(page.getByRole('columnheader', { name: 'Device' })).toHaveAttribute('aria-sort', 'ascending');
  await expect(page.locator('tbody tr strong').first()).toHaveText('compute-01.lab');
  await page.getByRole('button', { name: 'Device', exact: true }).click();
  await expect(page.locator('tbody tr strong').first()).toHaveText('workstation.lab');
  await page.reload();
  await expect(page.getByRole('columnheader', { name: 'Device' })).toHaveAttribute('aria-sort', 'descending');
  // The phone menu stays out of the tab order until it is opened.
  await page.setViewportSize({ width: 390, height: 844 });
  const nav = page.getByRole('navigation', { name: 'Main navigation' });
  await expect(nav).toBeHidden();
  await page.getByRole('button', { name: 'Toggle navigation' }).click();
  await expect(nav).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(nav).toBeHidden();
});

test('screenshot tour: every page, desktop and phone, dark and light', async ({ browser }) => {
  test.setTimeout(120_000);
  for (const theme of ['dark', 'light']) {
    for (const [width, height, size] of [[1440, 1000, 'desktop'], [390, 844, 'phone']] as const) {
      const context = await browser.newContext({ viewport: { width, height } });
      const page = await context.newPage();
      await page.addInitScript(value => localStorage.setItem('dragon-theme', value), theme);
      await signIn(page);
      const devices = await page.evaluate(() => fetch('/api/v1/devices?sort=ip').then(r => r.json()));
      const pages = { overview: '/', devices: '/devices', detail: `/devices/${devices.items[1].id}`, activity: '/activity', scans: '/scans', notifications: '/notifications', settings: '/settings' };
      for (const [name, path] of Object.entries(pages)) {
        await page.goto(path);
        await expect(page.locator('#content h1')).toBeVisible();
        await page.waitForLoadState('networkidle');
        await page.mouse.move(0, 0);
        await page.screenshot({ path: `../artifacts/tour/${name}-${size}-${theme}.png`, fullPage: true });
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `${name} fits ${size}`).toBe(true);
      }
      await context.close();
    }
  }
});
