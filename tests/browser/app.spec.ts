import { test, expect } from '../../frontend/node_modules/@playwright/test';

test('authenticated fixture inventory, quiet history, and administration', async ({ page }) => {
  const password = process.env.DRAGON_TEST_PASSWORD;
  if (!password) throw new Error('Set DRAGON_TEST_PASSWORD for the isolated fixture database');
  await page.goto('/');
  await page.getByLabel('Administrator password', { exact: true }).fill(password);
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'A little clarity. A lot less noise.' })).toBeVisible();
  await expect(page.getByText('Fixture workspace', { exact: true })).toBeVisible();
  await expect(page.getByRole('link', { name: /compute-01.lab|Fixture compute node/ })).toBeVisible();
  await page.setViewportSize({ width: 1440, height: 1100 });
  await page.screenshot({ path: '../artifacts/overview-desktop.png', fullPage: true });
  await page.getByRole('link', { name: /compute-01.lab|Fixture compute node/ }).click();
  await expect(page.getByRole('heading', { name: 'Last-known TCP ports' })).toBeVisible();
  await expect(page.getByText('closed', { exact: true })).toBeVisible();
  await page.getByLabel('Display name').fill('Fixture compute node');
  await page.getByRole('button', { name: 'Save details' }).click();
  await expect(page.getByRole('heading', { name: 'Fixture compute node' })).toBeVisible();
  await page.getByLabel('Display name').fill('');
  await page.getByRole('button', { name: 'Save details' }).click();
  await expect(page.getByRole('heading', { name: 'compute-01.lab' })).toBeVisible();
  await page.goto('/activity?category=ports');
  await page.getByRole('textbox', { name: 'Search event evidence' }).fill('8080');
  await expect(page.getByText(/port · state · TCP 8080/i)).toBeVisible();
  await expect(page.getByText(/port · state · TCP 3000/i)).not.toBeVisible();
  await page.goto('/notifications');
  await expect(page.getByText('Port and service changes never notify.', { exact: true })).toBeVisible();
  await page.goto('/scans');
  await expect(page.getByRole('button', { name: 'Queue scan' })).toBeDisabled();
  await page.goto('/settings');
  await expect(page.getByRole('heading', { name: 'Access & boundaries' })).toBeVisible();
  await page.goto('/');
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole('heading', { name: 'Quiet service history' })).toBeVisible();
  await page.screenshot({ path: '../artifacts/overview-mobile.png', fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.getByRole('button', { name: 'Toggle color theme' }).click();
  await page.screenshot({ path: '../artifacts/overview-light-mobile.png', fullPage: true });
  await page.getByRole('button', { name: 'Toggle navigation' }).click();
  await page.getByRole('button', { name: 'Sign out' }).click();
  await expect(page.getByRole('button', { name: 'Sign in', exact: true })).toBeVisible();
});

test('untrusted hostname is rendered as text', async ({ page }) => {
  await page.goto('/');
  await page.getByLabel('Administrator password', { exact: true }).fill(process.env.DRAGON_TEST_PASSWORD!);
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await page.getByRole('link', { name: /storage.lab/ }).click();
  const payload = '<img src=x onerror="window.dragonXss=true">';
  await page.getByLabel('Display name').fill(payload);
  await page.getByRole('button', { name: 'Save details' }).click();
  await expect(page.getByRole('heading', { name: payload })).toBeVisible();
  expect(await page.evaluate(() => (window as any).dragonXss)).toBeUndefined();
  await page.getByLabel('Display name').fill('');
  await page.getByRole('button', { name: 'Save details' }).click();
});

test('pagination follows the page size returned by the API', async ({ page }) => {
  await page.goto('/');
  await page.getByLabel('Administrator password', { exact: true }).fill(process.env.DRAGON_TEST_PASSWORD!);
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'A little clarity. A lot less noise.' })).toBeVisible();
  await page.route('**/api/v1/devices?**', async route => {
    const offset = Number(new URL(route.request().url()).searchParams.get('offset') || 0);
    await route.fulfill({ json: { items: [], total: 5, offset, limit: 2 } });
  });
  await page.goto('/devices');
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
