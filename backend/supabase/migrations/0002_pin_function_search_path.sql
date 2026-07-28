-- Security lint fix: pin search_path on SECURITY DEFINER-adjacent SQL
-- functions so it can't be hijacked by a caller-controlled search_path.
alter function public.get_demand(text) set search_path = public;
alter function public.get_role_counts() set search_path = public;
