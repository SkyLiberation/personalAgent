export const inject = ['agents']

export function apply(ctx, config) {
  ctx.on('agent/pre-step', ({ step }, next) => step > config.limit ? { kind: 'reject' } : next())
}
