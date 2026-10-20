-- Exécuté une seule fois, à la création du volume : la base de développement (POSTGRES_DB) existe
-- déjà ; on ajoute celle des tests, que `make test-pg` vide et recrée à chaque lancement.
CREATE DATABASE app_test;
