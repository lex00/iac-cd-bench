# Terraform Documentation Snippets

## Terraform State Management

Terraform state (.terraform.tfstate) tracks:
- Resource IDs and attributes
- Provider configurations
- Workspace information

### Key concepts:
- **Configuration** (.tf files): Desired state
- **State** (.tfstate): Current deployed state
- **Plan**: Difference between state and configuration

### State operations:
- `terraform plan`: Show planned changes
- `terraform apply`: Apply changes
- `terraform state`: Inspect state
- `terraform workspace`: Manage environments

## Terraform Modules

Modules organize reusable infrastructure:
- Root module: Main configuration
- Child modules: Reusable components
- Variables: Inputs to modules
- Outputs: Values exported from modules

### Best practices:
- Use `for_each` instead of `count` for dynamic resources
- Add `depends_on` for explicit dependencies
- Use `terraform import` to adopt existing resources

## Terraform Plan Behavior

Plan output shows:
- `+` for create, `-` for destroy, `~` for update
- `#` comments explain why changes are needed
- `replace` indicates destroy + create cycle
- `targeted` when using `--target` flag
