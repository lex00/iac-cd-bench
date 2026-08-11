# Pulumi Documentation Snippets

## Pulumi Architecture

Pulumi is an Infrastructure as Code platform that uses general-purpose programming languages.

### Key concepts:
- **Resources**: Cloud resources defined as objects
- **Stacks**: Isolated deployments with separate state
- **Outputs**: Values exported from stacks
- **Secrets**: Encrypted values in state

### Pulumi lifecycle:
1. `pulumi preview`: Show planned changes
2. `pulumi up`: Apply changes
3. `pulumi destroy`: Remove resources

## Pulumi Python SDK

### Core types:
- `Output<T>`: Represents a deferred value (not immediately available)
- `Input<T>`: Accepts literal values or Outputs
- `Secret`: Encrypted values (via `config.require_secret()`)
- `ComponentResource`: Custom resources composed of other resources

### Common pitfalls:
- Using `.apply()` incorrectly on Output values
- Mixing `async/await` with Pulumi's Output model
- Reading secrets as plain strings instead of `config.require_secret()`
- Not using `pulumi.export()` for outputs

## Pulumi TypeScript SDK

### Core types:
- `Output<T>`: Same as Python, deferred values
- `Input<T>`: Accepts literals or Outputs
- `Secret`: Encrypted values
- `ComponentResource`: Custom resources

### Common pitfalls:
- Using `async/await` on Outputs instead of `.apply()`
- Wrapping strings with `pulumi.output()` unnecessarily
- Not using `config.requireSecret()` for secrets
